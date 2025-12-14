import os.path
import subprocess
from pathlib import Path
from typing import Any, Callable

from trivialai import util


def _to_str(x):
    if x is None:
        return ""
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8", errors="replace")
    return x


def make_run_repo_tests_tool(repo_root: str) -> Callable[[], dict[str, Any]]:
    def run_repo_tests() -> dict[str, Any]:
        """
        Run this repository's unit test suite and return a structured result.

        Use this ONLY after you have written or modified tests.
        Do not call this repeatedly in a tight loop; usually once per file
        or per major change is enough.

        Returns a dict with keys:
          - status: "ok" if all tests passed, otherwise "fail" or "timeout"
          - exit_code: process exit code (if any)
          - stdout: captured test runner stdout (may be truncated)
          - stderr: captured test runner stderr (may be truncated)
        """
        python = os.path.join(repo_root, "env-robot_army", "bin", "python")
        try:
            proc = subprocess.run(
                [python, "-m", "unittest", "discover", "-s", "tests"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=300,  # seconds
            )
        except subprocess.TimeoutExpired as e:
            return {
                "status": "timeout",
                "exit_code": None,
                "stdout": _to_str(e.stdout),
                "stderr": _to_str(e.stderr) + "\n[timeout]",
            }

        def _trim(s: str, limit: int = 8000) -> str:
            if len(s) <= limit:
                return s
            return s[:limit] + "\n...[truncated]..."

        return {
            "status": "ok" if proc.returncode == 0 else "fail",
            "exit_code": proc.returncode,
            "stdout": _trim(_to_str(proc.stdout)),
            "stderr": _trim(_to_str(proc.stderr)),
        }

    return run_repo_tests


def make_tools(repo_root: Path) -> list[Callable[..., Any]]:
    """
    Build the standard toolset for a repo-root-clamped agent.

    Tools returned:
      - slurp(file_path: str) -> str | dict
      - spit(file_path: str, text: str, mode: str="w") -> dict
      - run_repo_tests() -> dict

    file_path may be absolute or relative, but it must resolve within repo_root.
    """
    root = repo_root

    def _resolve_repo_path(file_path: str) -> Path:
        """
        Resolve file_path as either:
          - absolute path (must still be within repo_root), or
          - relative to repo_root

        Reject anything outside repo_root (including symlink escapes).
        """
        raw = Path(str(file_path)).expanduser()
        candidate = raw if raw.is_absolute() else (root / raw)

        # resolve() is strict=False by default; OK for non-existent targets (writes)
        resolved = candidate.resolve()

        try:
            resolved.relative_to(root)
        except ValueError as e:
            raise ValueError(f"path-outside-repo: {file_path}") from e

        return resolved

    def slurp(file_path: str) -> Any:
        """
        Read a UTF-8 text file from within the repository.

        file_path may be relative to the repo root or absolute, but it must
        resolve inside the repo root.
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

        file_path may be relative to the repo root or absolute, but it must
        resolve inside the repo root.

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
