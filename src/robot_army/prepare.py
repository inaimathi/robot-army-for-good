# prepare.py
import subprocess
import sys
from pathlib import Path


def prepare_repo(agent, repo_root):
    """
    Prepare the target repository for property-based testing.

    Steps:
    1. Create a virtualenv named 'env-robot_army' in the repo root if it
       does not already exist.
    2. Use that virtualenv's Python to:
       - pip install -r requirements.txt (if it exists)
       - pip install .  (install the repo itself)
       - pip install hypothesis
    """
    root = Path(repo_root).expanduser().resolve()
    venv_dir = root / "env-robot_army"

    agent.log(
        {
            "type": "trivialai.agent.log",
            "message": f"Preparing repository at {root}",
        }
    )

    # 1. Create virtualenv if needed
    if not venv_dir.exists():
        agent.log(
            {
                "type": "trivialai.agent.log",
                "message": f"Creating virtualenv at {venv_dir}",
            }
        )
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            cwd=str(root),
        )
    else:
        agent.log(
            {
                "type": "trivialai.agent.log",
                "message": f"Virtualenv already exists at {venv_dir}",
            }
        )

    # POSIX-only path (no Windows branch)
    python = venv_dir / "bin" / "python"
    python_str = str(python)

    agent.log(
        {
            "type": "trivialai.agent.log",
            "message": f"Using Python interpreter: {python_str}",
        }
    )

    # Optionally upgrade pip
    try:
        agent.log(
            {
                "type": "trivialai.agent.log",
                "message": "Upgrading pip inside venv...",
            }
        )
        subprocess.run(
            [python_str, "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            cwd=str(root),
        )
    except subprocess.CalledProcessError:
        agent.log(
            {
                "type": "trivialai.agent.log",
                "message": "Warning: pip upgrade failed; continuing with existing pip.",
            }
        )

    # 2. pip install -r requirements.txt (if present)
    req_file = root / "requirements.txt"
    if req_file.exists():
        agent.log(
            {
                "type": "trivialai.agent.log",
                "message": "Installing requirements.txt into venv...",
            }
        )
        subprocess.run(
            [python_str, "-m", "pip", "install", "-r", "requirements.txt"],
            check=True,
            cwd=str(root),
        )
    else:
        agent.log(
            {
                "type": "trivialai.agent.log",
                "message": "No requirements.txt found; skipping requirements installation.",
            }
        )

    # 3. pip install . (install the repo itself)
    agent.log(
        {
            "type": "trivialai.agent.log",
            "message": "Installing repository (pip install .) into venv...",
        }
    )
    subprocess.run(
        [python_str, "-m", "pip", "install", "."],
        check=True,
        cwd=str(root),
    )

    # 4. pip install hypothesis
    agent.log(
        {
            "type": "trivialai.agent.log",
            "message": "Installing hypothesis into venv...",
        }
    )
    subprocess.run(
        [python_str, "-m", "pip", "install", "hypothesis"],
        check=True,
        cwd=str(root),
    )

    agent.log(
        {
            "type": "trivialai.agent.log",
            "message": "Repository preparation complete.",
        }
    )
