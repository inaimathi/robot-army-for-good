import os

from rafg.session import session_new, session_clone, session_run, session_finished

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

def catalog_test(github_project: str, filename: str) -> None:
    owner, repo = github_project.split("/")

    catalog_dir = f"{_catalog_root()}/{owner}/{repo}"
    session_id_file = f"{catalog_dir}/test/{filename}.txt"
    if not os.path.exists(f"{catalog_dir}/build/built"):
        raise FileNotFoundError(f"Catalog entry is not built: {catalog_dir}")

    if os.path.exists(session_id_file):
        print(f"Tests have already begun for file {filename} in project {github_project}")
        with open(session_id_file, "r") as f:
            session_id = f.read().strip()

        if session_finished(session_id):
            raise Exception(f"Session {session_id} has already finished all tests for file {filename}.")
        print(f"Resuming tests in existing session {session_id}...")
        instructions = _get_command("theft_continue", filename)
    else:
        with open(f"{catalog_dir}/build/session_id", "r") as f:
            old_session_id = f.read().strip()
        session_id = session_clone(old_session_id)
        print(f"Cloned session {old_session_id} to new session {session_id} for testing file {filename}")
        os.makedirs(os.path.dirname(session_id_file), exist_ok=True)
        with open(session_id_file, "w") as f:
            f.write(session_id)
        instructions = _get_command("theft", filename)
    
    session_run(session_id, instructions)

    print(f"Completed this round of testing for file {filename} for {github_project} with session ID: {session_id}")
    if session_finished(session_id):
        print(f"Session {session_id} has finished all tests.")