import os

from rafg.session import session_new, session_clone, session_run

def _catalog_root() -> str:
    return os.path.expanduser("~/catalog")

def _get_command(command_name: str, command_args: str) -> str:
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(script_dir, f"commands/{command_name}.md"), "r") as f:
        command_description = f.read()

    command_description = command_description.replace("$ARGUMENTS", command_args)
    return command_description

def catalog_new(github_project: str) -> None:
    owner, repo = github_project.split("/")

    catalog_dir = f"{_catalog_root()}/{owner}/{repo}"
    if os.path.exists(f"{catalog_dir}/build/session_id"):
        raise FileExistsError(f"Catalog entry already exists: {catalog_dir}")
    os.makedirs(catalog_dir, exist_ok=True)
    session_id = session_new(github_project)
    os.makedirs(f"{catalog_dir}/build", exist_ok=True)
    with open(f"{catalog_dir}/build/session_id", "w") as f:
        f.write(session_id)
    print(f"Created catalog entry for {github_project} with session ID: {session_id}")

def catalog_build(github_project: str) -> None:
    owner, repo = github_project.split("/")

    catalog_dir = f"{_catalog_root()}/{owner}/{repo}"
    if not os.path.exists(f"{catalog_dir}/build/session_id"):
        raise FileNotFoundError(f"Catalog entry does not exist: {catalog_dir}")
    if os.path.exists(f"{catalog_dir}/build/built"):
        raise FileExistsError(f"Catalog entry already built: {catalog_dir}")
    with open(f"{catalog_dir}/build/session_id", "r") as f:
        session_id = f.read().strip()
    print(f"Building catalog entry for {github_project} using session ID: {session_id}")

    instructions = _get_command("build_c", "")
    session_run(session_id, instructions)
    with open(f"{catalog_dir}/build/built", "w") as f:
        f.write("true")
    print(f"Completed building catalog entry for {github_project}")

def catalog_test(github_project: str, function: str) -> None:
    owner, repo = github_project.split("/")
    filename, function_name = function.split(":")

    catalog_dir = f"{_catalog_root()}/{owner}/{repo}"
    function_file = f"{catalog_dir}/test/{filename}/{function_name}"
    if not os.path.exists(f"{catalog_dir}/build/built"):
        raise FileNotFoundError(f"Catalog entry is not built: {catalog_dir}")
    if os.path.exists(function_file):
        raise FileExistsError(f"Catalog test function already exists: {function_file}")
    
    with open(f"{catalog_dir}/build/session_id", "r") as f:
        old_session_id = f.read().strip()
    new_session_id = session_clone(old_session_id)
    print(f"Cloned session {old_session_id} to new session {new_session_id} for testing function {function}")
    
    instructions = _get_command("theft", f"{filename} {function_name}")
    session_run(new_session_id, instructions)
    os.makedirs(os.path.dirname(function_file), exist_ok=True)
    with open(function_file, "w") as f:
        f.write(new_session_id)
    print(f"Completed testing function {function} for {github_project} with session ID: {new_session_id}")