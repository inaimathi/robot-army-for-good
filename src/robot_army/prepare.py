# prepare.py
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, TypeVar

from trivialai.log import getLogger

logger = getLogger("robot_army.prepare")
try:
    logger.propagate = False
except Exception:
    pass


PLAN_DIR = ".robot_army"
PLAN_FILE = "plan.json"
PROGRESS_FILE = "progress.ndjson"
DEFAULT_TIMEOUT_SEC = 900

T = TypeVar("T")


# ----------------------------- helpers ---------------------------------


def _which(bin_name: str) -> str | None:
    return shutil.which(bin_name)


def _missing_bins(bins: list[str]) -> list[str]:
    return [b for b in bins if _which(b) is None]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_plan(root: Path, plan: dict[str, Any]) -> Path:
    plan_dir = root / PLAN_DIR
    plan_dir.mkdir(parents=True, exist_ok=True)
    p = plan_dir / PLAN_FILE
    p.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update({str(k): str(v) for k, v in env.items()})

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=merged_env,
            timeout=timeout_sec,
        )
    except FileNotFoundError as e:
        exe = cmd[0] if cmd else "<empty-cmd>"
        raise RuntimeError(
            f"missing-executable: {exe}\n" f"  cmd: {cmd}\n" f"  cwd: {cwd}\n"
        ) from e

    if check and proc.returncode != 0:
        raise RuntimeError(
            "command-failed:\n"
            f"  cmd: {cmd}\n"
            f"  cwd: {cwd}\n"
            f"  exit_code: {proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def _slurpish(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _pick_libtoolize_bin() -> str | None:
    if _which("libtoolize"):
        return "libtoolize"
    if _which("glibtoolize"):
        return "glibtoolize"
    return None


def _unique_paths(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _guix_profile_aclocal_dirs() -> list[str]:
    home = Path.home()
    share = home / ".guix-profile" / "share"
    out: list[str] = []
    d = share / "aclocal"
    if d.is_dir():
        out.append(str(d))
    for p in share.glob("aclocal-*"):
        if p.is_dir():
            out.append(str(p))
    return out


def _autotools_env(
    base: dict[str, str] | None, *, add_aclocal_dirs: list[str]
) -> dict[str, str]:
    env = dict(base or {})
    env.setdefault("CI", "1")
    env.setdefault("LANG", "C")
    env.setdefault("LC_ALL", "C")

    # Respect base env first, then fall back to process env.
    existing = env.get("ACLOCAL_PATH") or os.environ.get("ACLOCAL_PATH", "")
    existing_parts = [p for p in existing.split(":") if p]
    new_parts = _unique_paths(add_aclocal_dirs + existing_parts)
    if new_parts:
        env["ACLOCAL_PATH"] = ":".join(new_parts)
    return env


# -------------------------- progress tracking ---------------------------


def _plan_hash(plan: dict[str, Any]) -> str:
    b = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()[:16]


def _progress_path(root: Path) -> Path:
    d = root / PLAN_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / PROGRESS_FILE


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


def _append_progress(root: Path, ev: dict[str, Any]) -> None:
    p = _progress_path(root)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, sort_keys=True) + "\n")


def _load_progress(root: Path) -> dict[str, dict[str, Any]]:
    """
    Returns latest record per event_id (last line wins).
    """
    p = _progress_path(root)
    if not p.exists():
        return {}

    latest: dict[str, dict[str, Any]] = {}
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            event_id = str(ev.get("event_id") or "")
            if not event_id:
                continue
            latest[event_id] = ev
    except Exception:
        return latest
    return latest


def _event_id(plan_h: str, name: str, payload: dict[str, Any]) -> str:
    # Deterministic + compact: event_id = <plan_hash>:<name>:<payload_hash>
    b = json.dumps(
        {"name": name, "payload": payload}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    ph = hashlib.sha256(b).hexdigest()[:12]
    return f"{plan_h}:{name}:{ph}"


def _step_done(progress: dict[str, dict[str, Any]], event_id: str) -> bool:
    return (progress.get(event_id) or {}).get("status") == "ok"


def _run_recorded_step(
    *,
    root: Path,
    progress: dict[str, dict[str, Any]],
    plan_h: str,
    name: str,
    payload: dict[str, Any],
    fn: Callable[[], T],
    nonfatal: bool = False,
) -> T | None:
    """
    Run a step once per (plan_hash, name, payload). If latest status is ok, skip.
    Records begin/ok/fail to .robot_army/progress.ndjson.
    """
    eid = _event_id(plan_h, name, payload)

    if _step_done(progress, eid):
        logger.info("Prepare skip (already ok): %s", name)
        return None

    begin = {
        "ts": _now_iso(),
        "event_id": eid,
        "name": name,
        "status": "begin",
        "payload": payload,
    }
    _append_progress(root, begin)
    progress[eid] = begin

    try:
        res = fn()
    except Exception as e:
        if nonfatal:
            logger.warning("Prepare nonfatal failure (marking ok): %s: %s", name, e)
            ok = {
                "ts": _now_iso(),
                "event_id": eid,
                "name": name,
                "status": "ok",
                "nonfatal": True,
                "error": str(e),
                "payload": payload,
            }
            _append_progress(root, ok)
            progress[eid] = ok
            return None

        fail = {
            "ts": _now_iso(),
            "event_id": eid,
            "name": name,
            "status": "fail",
            "error": str(e),
            "payload": payload,
        }
        _append_progress(root, fail)
        progress[eid] = fail
        raise

    ok = {
        "ts": _now_iso(),
        "event_id": eid,
        "name": name,
        "status": "ok",
        "payload": payload,
    }
    _append_progress(root, ok)
    progress[eid] = ok
    return res


def _run_recorded_cmd(
    *,
    root: Path,
    progress: dict[str, dict[str, Any]],
    plan_h: str,
    name: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    timeout_sec: int,
    check: bool = True,
    nonfatal: bool = False,
) -> subprocess.CompletedProcess[str] | None:
    payload = {
        "cmd": cmd,
        "cwd": str(cwd),
        "env": env or {},
        "timeout_sec": int(timeout_sec),
        "check": bool(check),
    }

    def _go() -> subprocess.CompletedProcess[str]:
        logger.info("Prepare cmd: %s", cmd)
        return _run_cmd(cmd, cwd=cwd, env=env, timeout_sec=timeout_sec, check=check)

    return _run_recorded_step(
        root=root,
        progress=progress,
        plan_h=plan_h,
        name=name,
        payload=payload,
        fn=_go,
        nonfatal=nonfatal,
    )


# -------------------------- autotools ----------------------------------


_LIBTOOL_UNDEFINED_RE = re.compile(
    r"Libtool library used but 'LIBTOOL' is undefined", re.I
)


def _autotools_fallback_sequence(
    root: Path,
    *,
    progress: dict[str, dict[str, Any]],
    plan_h: str,
    env: dict[str, str],
    timeout_sec: int,
) -> None:
    (root / "m4").mkdir(parents=True, exist_ok=True)

    steps = [
        ["aclocal", "-I", "m4"],
        ["autoconf"],
        ["automake", "--add-missing", "--copy"],
        ["autoconf"],
    ]
    for i, cmd in enumerate(steps):
        _run_recorded_cmd(
            root=root,
            progress=progress,
            plan_h=plan_h,
            name=f"autotools.fallback.{i}",
            cmd=cmd,
            cwd=root,
            env=env,
            timeout_sec=timeout_sec,
            check=True,
        )


def _autotools_bootstrap(
    root: Path,
    *,
    progress: dict[str, dict[str, Any]],
    plan_h: str,
    needs_autoreconf: bool,
    needs_libtoolize: bool,
    timeout_sec: int,
    configure_flags: list[str],
    base_env: dict[str, str] | None,
) -> None:
    # 0) submodules
    if (root / ".git").exists() and _which("git"):
        _run_recorded_cmd(
            root=root,
            progress=progress,
            plan_h=plan_h,
            name="git.submodule.update",
            cmd=["git", "submodule", "update", "--init", "--recursive"],
            cwd=root,
            env=base_env,
            timeout_sec=timeout_sec,
            check=True,
        )

    # 1) libtoolize (if needed)
    m4_dir = root / "m4"
    if needs_libtoolize:
        # harmless even if repeated / already present
        m4_dir.mkdir(parents=True, exist_ok=True)

        libtoolize_bin = _pick_libtoolize_bin()
        if not libtoolize_bin:
            raise RuntimeError(
                "missing-os-deps: repo appears to use libtool but libtoolize/glibtoolize not found"
            )

        env = _autotools_env(base_env, add_aclocal_dirs=_guix_profile_aclocal_dirs())
        _run_recorded_cmd(
            root=root,
            progress=progress,
            plan_h=plan_h,
            name="autotools.libtoolize",
            cmd=[libtoolize_bin, "--force", "--copy"],
            cwd=root,
            env=env,
            timeout_sec=timeout_sec,
            check=True,
        )

    # 2) autoreconf (if needed)
    if needs_autoreconf:
        env = _autotools_env(base_env, add_aclocal_dirs=_guix_profile_aclocal_dirs())

        cmd = ["autoreconf", "-fi"]
        if m4_dir.is_dir():
            cmd += ["-I", "m4"]

        # We want this whole “autoreconf with fallback” to be a single skip-able step.
        payload = {
            "cmd": cmd,
            "cwd": str(root),
            "env": env,
            "timeout_sec": int(timeout_sec),
        }

        def _autoreconf_with_fallback() -> None:
            try:
                _run_cmd(cmd, cwd=root, env=env, timeout_sec=timeout_sec, check=True)
            except RuntimeError as e:
                if _LIBTOOL_UNDEFINED_RE.search(str(e)):
                    logger.warning(
                        "autoreconf hit LIBTOOL undefined; retrying with explicit aclocal/autoconf/automake sequence"
                    )
                    _autotools_fallback_sequence(
                        root,
                        progress=progress,
                        plan_h=plan_h,
                        env=env,
                        timeout_sec=timeout_sec,
                    )
                else:
                    raise

        _run_recorded_step(
            root=root,
            progress=progress,
            plan_h=plan_h,
            name="autotools.autoreconf_or_fallback",
            payload=payload,
            fn=_autoreconf_with_fallback,
        )

    # 3) configure + build
    _run_recorded_cmd(
        root=root,
        progress=progress,
        plan_h=plan_h,
        name="autotools.configure",
        cmd=["./configure", *configure_flags],
        cwd=root,
        env=base_env,
        timeout_sec=timeout_sec,
        check=True,
    )

    jobs = max(2, (os.cpu_count() or 4))
    _run_recorded_cmd(
        root=root,
        progress=progress,
        plan_h=plan_h,
        name="autotools.make",
        cmd=["make", f"-j{jobs}"],
        cwd=root,
        env=base_env,
        timeout_sec=timeout_sec,
        check=True,
    )


# --------------------------- plan detection -----------------------------


def _plan_node(root: Path) -> dict[str, Any]:
    pkg = _read_json(root / "package.json")
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}

    if (root / "pnpm-lock.yaml").exists():
        pm = "pnpm"
        install_cmd = [pm, "install", "--frozen-lockfile"]
    elif (root / "yarn.lock").exists():
        pm = "yarn"
        install_cmd = [pm, "install", "--frozen-lockfile"]
    else:
        pm = "npm"
        install_cmd = (
            ["npm", "ci"]
            if (root / "package-lock.json").exists()
            else ["npm", "install"]
        )

    cm = root / "bin" / "cm.js"
    prepare_cmds: list[list[str]] = []
    notes: list[str] = []

    if cm.exists():
        prepare_cmds.append(["node", "bin/cm.js", "install"])
        notes.append(
            "Detected bin/cm.js; using CodeMirror-style bootstrap: node bin/cm.js install"
        )
    else:
        prepare_cmds.append(install_cmd)

    test_cmds: list[list[str]] = []
    if isinstance(scripts, dict) and "test-node" in scripts:
        test_cmds.append([pm, "run", "test-node"])
    elif isinstance(scripts, dict) and "test" in scripts:
        test_cmds.append([pm, "test"])
    else:
        notes.append(
            "No test or test-node script found in package.json; test command list is empty."
        )

    # Corepack-aware required bin set:
    bins_required: list[str] = ["node"]
    bins_optional: list[str] = []

    if pm == "npm":
        bins_required.append("npm")
    else:
        if _which(pm) is not None:
            bins_required.append(pm)
        elif _which("corepack") is not None:
            # We'll enable corepack as part of prepare steps; don't fail bins_required up front.
            prepare_cmds.insert(0, ["corepack", "enable"])
            bins_required.append("corepack")
            bins_optional.append(pm)
            notes.append(f"{pm} not found; using corepack enable before running {pm}.")
        else:
            # No corepack and pm missing => hard missing
            bins_required.append(pm)

    return {
        "kind": "node",
        "os_deps": {"bins_required": bins_required, "bins_optional": bins_optional},
        "env": {"CI": "1"},
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "prepare": prepare_cmds,
        "test": test_cmds,
        "notes": notes,
    }


def _plan_python(root: Path) -> dict[str, Any]:
    venv_dir = root / "env-robot_army"
    python = venv_dir / "bin" / "python"

    prepare_cmds: list[list[str]] = []
    if not venv_dir.exists():
        prepare_cmds.append([sys.executable, "-m", "venv", str(venv_dir)])

    prepare_cmds.append([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    if (root / "requirements.txt").exists():
        prepare_cmds.append(
            [str(python), "-m", "pip", "install", "-r", "requirements.txt"]
        )
    prepare_cmds.append([str(python), "-m", "pip", "install", "."])
    prepare_cmds.append([str(python), "-m", "pip", "install", "hypothesis"])

    test_cmds = [[str(python), "-m", "unittest", "discover", "-s", "tests"]]
    return {
        "kind": "python",
        "os_deps": {"bins_required": [], "bins_optional": ["python3"]},
        "env": {"CI": "1"},
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "prepare": prepare_cmds,
        "test": test_cmds,
        "notes": [],
    }


def _plan_c_autotools(root: Path) -> dict[str, Any]:
    cfg = root / "configure"
    cfg_ac = root / "configure.ac"
    cfg_in = root / "configure.in"
    autogen = root / "autogen.sh"

    needs_autoreconf = (not cfg.exists()) and (
        cfg_ac.exists() or cfg_in.exists() or autogen.exists()
    )

    ac_text = _slurpish(cfg_ac) + "\n" + _slurpish(cfg_in)
    make_am = (
        _slurpish(root / "src" / "Makefile.am") + "\n" + _slurpish(root / "Makefile.am")
    )
    needs_libtoolize = (
        ("LT_INIT" in ac_text)
        or ("AC_PROG_LIBTOOL" in ac_text)
        or ("LTLIBRARIES" in make_am)
    )

    configure_flags: list[str] = []
    if "oniguruma" in (_slurpish(cfg) + _slurpish(cfg_ac)):
        configure_flags.append("--with-oniguruma=builtin")

    bins_required = ["make"]
    if (root / ".git").exists():
        bins_required.append("git")
    if needs_libtoolize:
        bins_required.append("libtool")
        bins_required.append(_pick_libtoolize_bin() or "libtoolize")
    if needs_autoreconf:
        bins_required.extend(["autoreconf", "autoconf", "automake", "aclocal"])

    bins_optional = ["pkg-config", "gcc", "cc", "clang", "m4"]

    prepare_cmds: list[list[str]] = []
    if (root / ".git").exists():
        prepare_cmds.append(["git", "submodule", "update", "--init", "--recursive"])
    if needs_libtoolize:
        prepare_cmds.append(
            [_pick_libtoolize_bin() or "libtoolize", "--force", "--copy"]
        )
    if needs_autoreconf:
        prepare_cmds.append(["autoreconf", "-fi", "-I", "m4"])
    prepare_cmds.append(["./configure", *configure_flags])
    prepare_cmds.append(["make", "-jN"])
    test_cmds = [["make", "check"], ["make", "test"]]

    return {
        "kind": "c-autotools",
        "os_deps": {"bins_required": bins_required, "bins_optional": bins_optional},
        "env": {"CI": "1", "LANG": "C", "LC_ALL": "C"},
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "autotools": {
            "needs_autoreconf": needs_autoreconf,
            "needs_libtoolize": needs_libtoolize,
            "configure_flags": configure_flags,
        },
        "prepare": prepare_cmds,
        "test": test_cmds,
        "notes": [],
    }


def _detect_plan(root: Path) -> dict[str, Any]:
    if (root / "package.json").exists():
        return _plan_node(root)
    if (
        (root / "configure.ac").exists()
        or (root / "autogen.sh").exists()
        or (root / "configure").exists()
    ):
        return _plan_c_autotools(root)
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return _plan_python(root)

    return {
        "kind": "unknown",
        "os_deps": {"bins_required": []},
        "env": {"CI": "1"},
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "prepare": [],
        "test": [],
        "notes": ["No supported build/test system detected."],
    }


# ----------------------------- prepare_repo --------------------------------


def prepare_repo(repo_root: str) -> dict[str, Any]:
    """
    Prepare repo and write `.robot_army/plan.json`.

    Idempotency:
      - Progress is tracked in `.robot_army/progress.ndjson` (append-only).
      - Each step has a deterministic event_id derived from:
            plan_hash + (step_name, payload)
      - A step is skipped if the *latest* record for that event_id has status == "ok".
      - If a run is interrupted after "begin" but before "ok", the next run will re-attempt.

    To force a full re-run:
      - delete `.robot_army/progress.ndjson` (and optionally plan.json).
    """
    root = Path(repo_root).expanduser().resolve()
    logger.info("Preparing repository at %s", root)

    plan = _detect_plan(root)
    plan_path = _write_plan(root, plan)
    plan_h = _plan_hash(plan)

    logger.info(
        "Wrote plan: %s (kind=%s, plan_hash=%s)", plan_path, plan.get("kind"), plan_h
    )

    progress = _load_progress(root)

    # 1) OS-level deps check (recorded so it won't re-run once successful)
    def _os_deps_check() -> None:
        os_deps = plan.get("os_deps") or {}
        missing_req = _missing_bins(list(os_deps.get("bins_required") or []))
        if missing_req:
            raise RuntimeError(
                f"missing-os-deps: required binaries not found on PATH: {missing_req}"
            )

        missing_opt = _missing_bins(list(os_deps.get("bins_optional") or []))
        if missing_opt:
            logger.warning(
                "Optional binaries not found (may reduce success rate): %s", missing_opt
            )

    _run_recorded_step(
        root=root,
        progress=progress,
        plan_h=plan_h,
        name="os_deps.check",
        payload={
            "bins_required": (plan.get("os_deps") or {}).get("bins_required", []),
            "bins_optional": (plan.get("os_deps") or {}).get("bins_optional", []),
        },
        fn=_os_deps_check,
    )

    # 2) Language-level prep (record each command, so successful ones never re-run)
    env = plan.get("env") or {"CI": "1"}
    timeout_sec = int(plan.get("timeout_sec") or DEFAULT_TIMEOUT_SEC)
    kind = str(plan.get("kind") or "")

    if kind == "c-autotools":
        auto = plan.get("autotools") or {}
        _autotools_bootstrap(
            root,
            progress=progress,
            plan_h=plan_h,
            needs_autoreconf=bool(auto.get("needs_autoreconf")),
            needs_libtoolize=bool(auto.get("needs_libtoolize")),
            timeout_sec=timeout_sec,
            configure_flags=list(auto.get("configure_flags") or []),
            base_env=env,
        )
    else:
        for i, cmd in enumerate(plan.get("prepare") or []):
            # Preserve your prior behavior: pip upgrade failures are non-fatal,
            # but now we also mark them OK so we don't spam/retry every run.
            nonfatal = False
            if kind == "python" and cmd[-3:] == ["install", "--upgrade", "pip"]:
                nonfatal = True

            _run_recorded_cmd(
                root=root,
                progress=progress,
                plan_h=plan_h,
                name=f"prepare.{i}",
                cmd=cmd,
                cwd=root,
                env=env,
                timeout_sec=timeout_sec,
                check=True,
                nonfatal=nonfatal,
            )

    logger.info("Repository preparation complete.")
    return plan
