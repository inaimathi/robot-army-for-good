# prepare.py
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from trivialai.log import getLogger

logger = getLogger("robot_army.prepare")
# If your logging is showing duplicates, this usually stops “bubble up” duplication.
# (If duplicates persist, you likely have multiple handlers attached upstream.)
try:
    logger.propagate = False
except Exception:
    pass


PLAN_DIR = ".robot_army"
PLAN_FILE = "plan.json"
DEFAULT_TIMEOUT_SEC = 900


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
    # GNU libtoolize (Linux) vs glibtoolize (macOS/Homebrew)
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
    """
    On Guix, aclocal macros often live under ~/.guix-profile/share/aclocal
    and sometimes also ~/.guix-profile/share/aclocal-<ver>.
    """
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
    """
    Ensure ACLOCAL_PATH includes Guix-profile macro dirs (and anything else we pass).
    This is the key fix for the persistent:
      "Libtool library used but 'LIBTOOL' is undefined"
    when using Guix-provided libtool/autotools.
    """
    env = dict(base or {})
    # Keep locale predictable (also silences perl locale spam).
    env.setdefault("CI", "1")
    env.setdefault("LANG", "C")
    env.setdefault("LC_ALL", "C")

    existing = env.get("ACLOCAL_PATH") or os.environ.get("ACLOCAL_PATH", "")
    existing_parts = [p for p in existing.split(":") if p]
    new_parts = _unique_paths(add_aclocal_dirs + existing_parts)
    if new_parts:
        env["ACLOCAL_PATH"] = ":".join(new_parts)
    return env


_LIBTOOL_UNDEFINED_RE = re.compile(
    r"Libtool library used but 'LIBTOOL' is undefined", re.I
)


def _autotools_bootstrap(
    root: Path,
    *,
    needs_autoreconf: bool,
    needs_libtoolize: bool,
    timeout_sec: int,
    configure_flags: list[str],
    base_env: dict[str, str] | None,
) -> None:
    """
    Robust autotools bootstrap with an out-of-the-box fix for the libtool macro issue.

    Strategy:
      - if libtool is likely used:
          * ensure m4/ exists
          * run libtoolize --force --copy
      - run autoreconf -fi (and *also* provide macro include dirs)
          * env ACLOCAL_PATH includes ~/.guix-profile/share/aclocal (+ aclocal-*)
          * pass -I m4 so aclocal searches the local macro dir too
      - if it still fails with LIBTOOL undefined:
          * fallback to an explicit sequence:
                aclocal -I m4
                autoconf
                automake --add-missing --copy
                autoconf
    """
    # 0) submodules (common for jq)
    if (root / ".git").exists() and _which("git"):
        logger.info(
            "Prepare cmd: %s", ["git", "submodule", "update", "--init", "--recursive"]
        )
        _run_cmd(
            ["git", "submodule", "update", "--init", "--recursive"],
            cwd=root,
            env=base_env,
            timeout_sec=timeout_sec,
            check=True,
        )

    # 1) libtoolize (if needed)
    m4_dir = root / "m4"
    if needs_libtoolize:
        m4_dir.mkdir(parents=True, exist_ok=True)
        libtoolize_bin = _pick_libtoolize_bin()
        if not libtoolize_bin:
            raise RuntimeError(
                "missing-os-deps: repo appears to use libtool but libtoolize/glibtoolize not found"
            )

        logger.info("Prepare cmd: %s", [libtoolize_bin, "--force", "--copy"])
        _run_cmd(
            [libtoolize_bin, "--force", "--copy"],
            cwd=root,
            env=_autotools_env(base_env, add_aclocal_dirs=_guix_profile_aclocal_dirs()),
            timeout_sec=timeout_sec,
            check=True,
        )

    # 2) autoreconf (if needed)
    if needs_autoreconf:
        # Crucial: make sure aclocal can see guix-profile macro dirs.
        env = _autotools_env(base_env, add_aclocal_dirs=_guix_profile_aclocal_dirs())
        cmd = ["autoreconf", "-fi"]
        # Always include local macro dir if it exists / we created it.
        if m4_dir.is_dir():
            cmd += ["-I", "m4"]

        logger.info("Prepare cmd: %s", cmd)
        try:
            _run_cmd(cmd, cwd=root, env=env, timeout_sec=timeout_sec, check=True)
        except RuntimeError as e:
            msg = str(e)
            if _LIBTOOL_UNDEFINED_RE.search(msg):
                logger.warning(
                    "autoreconf hit LIBTOOL undefined; retrying with explicit aclocal/autoconf/automake sequence"
                )
                _autotools_fallback_sequence(root, env=env, timeout_sec=timeout_sec)
            else:
                raise

    # 3) configure + build
    logger.info("Prepare cmd: %s", ["./configure", *configure_flags])
    _run_cmd(
        ["./configure", *configure_flags],
        cwd=root,
        env=base_env,
        timeout_sec=timeout_sec,
        check=True,
    )

    jobs = max(2, (os.cpu_count() or 4))
    logger.info("Prepare cmd: %s", ["make", f"-j{jobs}"])
    _run_cmd(
        ["make", f"-j{jobs}"],
        cwd=root,
        env=base_env,
        timeout_sec=timeout_sec,
        check=True,
    )


def _autotools_fallback_sequence(
    root: Path, *, env: dict[str, str], timeout_sec: int
) -> None:
    """
    Last-resort explicit sequence that bypasses some of autoreconf’s “best effort”.
    """
    # Ensure m4 exists if we’re going to include it.
    (root / "m4").mkdir(parents=True, exist_ok=True)

    steps = [
        ["aclocal", "-I", "m4"],
        ["autoconf"],
        ["automake", "--add-missing", "--copy"],
        ["autoconf"],
    ]
    for cmd in steps:
        logger.info("Prepare cmd: %s", cmd)
        _run_cmd(cmd, cwd=root, env=env, timeout_sec=timeout_sec, check=True)


# --------------------------- plan detection --------------------------------


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

    bins_required = ["node", "npm"] if pm == "npm" else ["node", pm]
    bins_optional: list[str] = []
    if pm in ("pnpm", "yarn") and _which(pm) is None and _which("corepack") is not None:
        prepare_cmds.insert(0, ["corepack", "enable"])
        bins_optional.append(pm)

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
    # Also scan Makefile.am patterns that strongly imply libtool usage.
    make_am = (
        _slurpish(root / "src" / "Makefile.am") + "\n" + _slurpish(root / "Makefile.am")
    )
    needs_libtoolize = (
        ("LT_INIT" in ac_text)
        or ("AC_PROG_LIBTOOL" in ac_text)
        or ("LTLIBRARIES" in make_am)
    )

    configure_flags: list[str] = []
    # jq-specific helpful flag (detected heuristically)
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

    # We keep prepare/test lists in the plan (for visibility), but the *execution*
    # of autotools prep is handled by _autotools_bootstrap for robustness.
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

    Key autotools robustness:
      - Always inject ACLOCAL_PATH to include Guix profile macro dirs.
      - Run libtoolize + autoreconf with -I m4 when libtool usage is detected.
      - If LIBTOOL undefined still occurs, fall back to explicit aclocal/autoconf/automake sequence.
    """
    root = Path(repo_root).expanduser().resolve()
    logger.info("Preparing repository at %s", root)

    plan = _detect_plan(root)
    plan_path = _write_plan(root, plan)
    logger.info("Wrote plan: %s (kind=%s)", plan_path, plan.get("kind"))

    # 1) OS-level deps check
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

    # 2) Language-level prep
    env = plan.get("env") or {"CI": "1"}
    timeout_sec = int(plan.get("timeout_sec") or DEFAULT_TIMEOUT_SEC)
    kind = str(plan.get("kind") or "")

    if kind == "c-autotools":
        auto = plan.get("autotools") or {}
        _autotools_bootstrap(
            root,
            needs_autoreconf=bool(auto.get("needs_autoreconf")),
            needs_libtoolize=bool(auto.get("needs_libtoolize")),
            timeout_sec=timeout_sec,
            configure_flags=list(auto.get("configure_flags") or []),
            base_env=env,
        )
    else:
        # generic execution for node/python/etc
        for cmd in plan.get("prepare") or []:
            logger.info("Prepare cmd: %s", cmd)
            try:
                _run_cmd(cmd, cwd=root, env=env, timeout_sec=timeout_sec, check=True)
            except RuntimeError:
                # keep your prior behavior: pip upgrade failures are non-fatal
                if kind == "python" and cmd[-3:] == ["install", "--upgrade", "pip"]:
                    logger.warning("pip upgrade failed; continuing with existing pip.")
                    continue
                raise

    logger.info("Repository preparation complete.")
    return plan
