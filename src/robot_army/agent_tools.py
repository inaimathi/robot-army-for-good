# agent_tools.py
from __future__ import annotations

import json
import os
import os.path
import subprocess
from pathlib import Path
from typing import Any, Callable

from trivialai import util

# ----------------------------- small helpers -----------------------------


def _to_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8", errors="replace")
    return str(x)


def _trim(s: str, limit: int = 8000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "\n...[truncated]..."


def _is_within_repo(repo_root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(repo_root.resolve())
        return True
    except Exception:
        return False


def _normalize_cmd(cmd: Any) -> list[str] | None:
    """
    Expect plan commands to be JSON arrays of strings, e.g. ["make","check"].
    We intentionally do NOT accept a single shell string.
    """
    if not isinstance(cmd, list) or not cmd:
        return None
    out: list[str] = []
    for x in cmd:
        if not isinstance(x, str) or not x:
            return None
        out.append(x)
    return out


def _cmd_allowed(kind: str, repo_root: Path, cmd: list[str]) -> bool:
    """
    Safety gate: the agent can edit repo files, so we don't blindly execute
    arbitrary commands out of .robot_army/plan.json.

    Allow a small set of known test runners per kind.
    """
    exe = cmd[0]

    # Allow absolute executables only if they live inside the repo root
    # (e.g. env-robot_army/bin/python).
    if os.path.isabs(exe) and not _is_within_repo(repo_root, Path(exe)):
        return False

    if kind == "python":
        # expected: <repo>/env-robot_army/bin/python -m unittest discover -s tests
        if (
            exe.endswith("/env-robot_army/bin/python")
            or exe == "python"
            or exe.endswith("/python")
        ):
            return ("-m" in cmd and "unittest" in cmd) or ("pytest" in cmd)
        return False

    if kind == "node":
        # expected: npm/yarn/pnpm test OR npm/yarn/pnpm run <script>
        if exe in ("npm", "yarn", "pnpm"):
            return len(cmd) >= 2 and cmd[1] in ("test", "run")
        # allow codemirror-style: node bin/cm.js test ...
        if exe == "node":
            return (
                len(cmd) >= 3
                and cmd[1].endswith("bin/cm.js")
                and cmd[2] in ("test", "build", "lint")
            )
        return False

    if kind.startswith("c-"):
        # expected: make check (and sometimes ctest later)
        if exe == "make":
            return len(cmd) >= 2 and cmd[1] in ("check", "test")
        if exe == "ctest":
            return True
        return False

    # Unknown: allow only a conservative subset
    if exe == "make":
        return len(cmd) >= 2 and cmd[1] in ("check", "test")
    if exe in ("npm", "yarn", "pnpm"):
        return len(cmd) >= 2 and cmd[1] in ("test", "run")
    return False


def _should_try_next(cmd: list[str], returncode: int, stdout: str, stderr: str) -> bool:
    """
    IMPORTANT: Only fall back to the next candidate command when the failure looks like
    'this runner/target doesn't exist', NOT when the tests actually failed.

    This fixes the jq case:
      - make check runs and fails (tests failing) => should RETURN that output
      - not proceed to make test (which doesn't exist) and mask the real output
    """
    combined = (stderr or "") + "\n" + (stdout or "")

    # make: fall back only if target doesn't exist
    if cmd and cmd[0] == "make" and len(cmd) >= 2:
        if "No rule to make target" in combined:
            return True
        return False

    # npm/yarn/pnpm: fall back only if script missing
    if cmd and cmd[0] in ("npm", "yarn", "pnpm"):
        if "Missing script:" in combined or "missing script" in combined.lower():
            return True
        return False

    return False


# ----------------------------- run_repo_tests -----------------------------


def make_run_repo_tests_tool(repo_root: str) -> Callable[[], dict[str, Any]]:
    root = Path(repo_root).expanduser().resolve()
    plan_path = root / ".robot_army" / "plan.json"

    def run_repo_tests() -> dict[str, Any]:
        """
        Run this repository's test suite (as configured by prepare_repo) and return
        a structured result.

        Returns a dict with keys:
          - status: "ok" if all tests passed, otherwise "fail" or "timeout"
          - exit_code: process exit code (if any)
          - stdout: captured test runner stdout (may be truncated)
          - stderr: captured test runner stderr (may be truncated)

        Extra keys:
          - cmd: the command that was executed
          - attempted_cmds: list of candidate commands (if fallbacks exist)
          - cwd: working directory used
          - error/message: if configuration is missing/invalid
        """
        # Prefer the prepared plan.
        plan: dict[str, Any] | None = None
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except Exception as e:
                return {
                    "status": "fail",
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "error": "invalid-plan",
                    "message": str(e),
                    "cwd": str(root),
                }

        # Back-compat fallback: python-only behavior if plan is missing.
        if not plan:
            python = root / "env-robot_army" / "bin" / "python"
            attempted = [[str(python), "-m", "unittest", "discover", "-s", "tests"]]
            timeout_sec = 300
            trim_limit = 8000
            env = os.environ.copy()
            kind = "python"
        else:
            kind = str(plan.get("kind") or "unknown")
            timeout_sec = int(plan.get("timeout_sec") or 300)
            trim_limit = int(plan.get("trim_limit") or 8000)

            env = os.environ.copy()
            plan_env = plan.get("env") or {}
            if isinstance(plan_env, dict):
                for k, v in plan_env.items():
                    env[str(k)] = str(v)

            raw_tests = plan.get("test") or []
            if not isinstance(raw_tests, list) or not raw_tests:
                return {
                    "status": "fail",
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "error": "no-test-commands",
                    "message": f"{plan_path} has no test commands",
                    "cwd": str(root),
                }

            attempted = []
            for raw in raw_tests:
                cmd = _normalize_cmd(raw)
                if cmd is None:
                    return {
                        "status": "fail",
                        "exit_code": None,
                        "stdout": "",
                        "stderr": "",
                        "error": "bad-test-command",
                        "message": f"Expected list[str], got: {raw!r}",
                        "cwd": str(root),
                    }
                if not _cmd_allowed(kind, root, cmd):
                    return {
                        "status": "fail",
                        "exit_code": None,
                        "stdout": "",
                        "stderr": "",
                        "error": "disallowed-test-command",
                        "message": f"Refusing to execute command for kind={kind!r}: {cmd!r}",
                        "cwd": str(root),
                    }
                attempted.append(cmd)

        last: dict[str, Any] | None = None

        for cmd in attempted:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=env,
                )
            except subprocess.TimeoutExpired as e:
                return {
                    "status": "timeout",
                    "exit_code": None,
                    "cmd": cmd,
                    "attempted_cmds": attempted,
                    "cwd": str(root),
                    "stdout": _trim(_to_str(e.stdout), trim_limit),
                    "stderr": _trim(_to_str(e.stderr) + "\n[timeout]", trim_limit),
                }
            except FileNotFoundError as e:
                # Runner missing (e.g. make/npm not installed). This is safe to fall back from.
                res = {
                    "status": "fail",
                    "exit_code": None,
                    "cmd": cmd,
                    "attempted_cmds": attempted,
                    "cwd": str(root),
                    "stdout": "",
                    "stderr": f"{type(e).__name__}: {e}",
                    "error": "missing-executable",
                }
                last = res
                continue

            res = {
                "status": "ok" if proc.returncode == 0 else "fail",
                "exit_code": proc.returncode,
                "cmd": cmd,
                "attempted_cmds": attempted,
                "cwd": str(root),
                "stdout": _trim(_to_str(proc.stdout), trim_limit),
                "stderr": _trim(_to_str(proc.stderr), trim_limit),
            }
            last = res

            if proc.returncode == 0:
                return res

            # ✅ Only try the next fallback if this looks like "runner/target missing"
            if not _should_try_next(cmd, proc.returncode, res["stdout"], res["stderr"]):
                return res

        return last or {
            "status": "fail",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": "no-attempts",
            "message": "No commands were executed",
            "cwd": str(root),
        }

    return run_repo_tests


# ----------------------------- make_tools ----------------------------------


def make_tools(repo_root: Path) -> list[Callable[..., Any]]:
    """
    Build the standard toolset for a repo-root-clamped agent.

    Tools returned:
      - slurp(file_path: str) -> str | dict
      - spit(file_path: str, text: str, mode: str="w") -> dict
      - run_repo_tests() -> dict

    file_path may be absolute or relative, but it must resolve within repo_root.
    """
    root = Path(repo_root).expanduser().resolve()

    def _resolve_repo_path(file_path: str) -> Path:
        raw = Path(str(file_path)).expanduser()
        candidate = raw if raw.is_absolute() else (root / raw)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as e:
            raise ValueError(f"path-outside-repo: {file_path}") from e
        return resolved

    def slurp(file_path: str) -> Any:
        """
        Read a UTF-8 text file from within the repository.
        """
        try:
            p = _resolve_repo_path(file_path)
            return util.slurp(str(p))
        except Exception as e:
            return {
                "status": "fail",
                "error": type(e).__name__,
                "message": str(e),
                "file_path": file_path,
            }

    def spit(file_path: str, text: str, mode: str = "w") -> dict[str, Any]:
        """
        Write UTF-8 text to a file within the repository.
        mode defaults to "w" (overwrite). Use "a" to append.
        """
        try:
            p = _resolve_repo_path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            util.spit(str(p), text, mode=mode)
            return {
                "status": "ok",
                "file_path": str(p),
                "mode": mode,
                "bytes": len(text),
            }
        except Exception as e:
            return {
                "status": "fail",
                "error": type(e).__name__,
                "message": str(e),
                "file_path": file_path,
                "mode": mode,
            }

    run_repo_tests = make_run_repo_tests_tool(str(root))
    return [slurp, spit, run_repo_tests]
