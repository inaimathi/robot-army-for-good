import argparse
import json
import os
import shutil
from uuid import uuid4, UUID
import subprocess
import datetime
from contextlib import contextmanager

def kludgy_uuid7() -> UUID:
    # Generate a UUIDv7-like string using current timestamp and random bits
    timestamp = int(datetime.datetime.now().timestamp() * 1000)
    timestamp_hex = f"{timestamp:012x}"
    random_hex_and_var = uuid4().hex[13:]
    return UUID(timestamp_hex + "7" + random_hex_and_var)

def gen_session_id() -> str:
    # return the date and time with a few random characters appended
    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    random_str = uuid4().hex[:6]
    return f"{date_str}_{random_str}"

def github_clone(session_id: str, project: str, project_dir: str):
    print(f"Cloning GitHub project: {project}")
    os.makedirs(session_id, exist_ok=False)

    subprocess.run(["git", "clone", f"https://github.com/{project}.git", f"{session_id}/{project_dir}"], check=True)

def run_codex(session_dir: str, project_name: str, command: str = "theft", command_args: str = ""):
    print(f"Running Codex on project directory: {session_dir}/{project_name}\n  command: /{command} {command_args}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, f"commands/{command}.md"), "r") as f:
        command_description = f.read()

    command_description = command_description.replace("$ARGUMENTS", command_args)

    subprocess.run(["codex",
                        "--ask-for-approval", "never",
                        "exec",
                        "--sandbox", "workspace-write",
                        "-"
                    ], cwd=f"{session_dir}/{project_name}", check=True, input=command_description.encode("utf-8"))

def codex_session_to_filename(codex_session_id: str) -> str:
    u = UUID(codex_session_id)
    timestamp_hex = u.hex[:12]
    timestamp = int(timestamp_hex, 16)
    filename = datetime.datetime.fromtimestamp(timestamp/1000, datetime.timezone.utc).strftime(".codex/sessions/%Y/%m/%d/rollout-%Y-%m-%dT%H-%M-%S-")
    filename += f"{codex_session_id}.jsonl"
    return filename

def clone_codex_session(codex_session_id: str) -> str:
    orig_filename = codex_session_to_filename(codex_session_id)
    if not os.path.exists(orig_filename):
        raise FileNotFoundError(f"Codex session file not found: {orig_filename}")
    
    new_session_id = str(kludgy_uuid7())
    new_filename = codex_session_to_filename(new_session_id)
    print(f"Cloning Codex session: {orig_filename} to {new_filename}")

    with open(orig_filename, "r") as f_in:
        text = f_in.read().replace(codex_session_id, new_session_id)

    os.makedirs(os.path.dirname(new_filename), exist_ok=True)
    with open(new_filename, "w") as f_out:
        f_out.write(text)
    return new_session_id

@contextmanager
def cloned_session(codex_session_id: str):
    new_session_id = clone_codex_session(codex_session_id)
    with open(codex_session_to_filename(new_session_id), "r") as f:
        line = f.readline()
        orig_cwd = json.loads(line)["payload"]["cwd"]
    print("Cloned session ID:", new_session_id)
    print("Original CWD:", orig_cwd)
    project_name = os.path.basename(orig_cwd)
    print("Project name:", project_name)
    orig_dir = os.path.dirname(orig_cwd)
    temp_copy = orig_dir + "_original"
    if os.path.exists(temp_copy):
        raise FileExistsError(f"Temporary directory copy already exists: {temp_copy}")
    new_dir = new_session_id
    if os.path.exists(new_dir):
        raise FileExistsError(f"New session directory already exists: {new_dir}")
    print("Creating copy of original CWD at:", f"{temp_copy}/{project_name}")
    os.makedirs(temp_copy, exist_ok=False)
    shutil.copytree(f"{orig_dir}/{project_name}", f"{temp_copy}/{project_name}")
    try:
        yield orig_dir, project_name
    finally:
        print(f"Moving project directory {orig_dir} to {new_dir}")
        shutil.move(orig_dir, new_dir)
        print(f"Restoring original CWD from temporary copy {temp_copy} to {orig_dir}")
        shutil.move(temp_copy, orig_dir)


def run_build(args):
    session_id = gen_session_id()
    print("Session ID:", session_id)

    project = args.project
    project_dir = project.split("/")[-1]
    print(f"Building tests for project: {project}")
    github_clone(session_id, project, project_dir)
    run_codex(session_id, project_dir, command="build_c", command_args="")

def run_test(args):
    with cloned_session(args.codex_session_id) as (session_dir, project_name):
        print(f"Generating and running tests for project: {project_name}, function: {args.function}")
        run_codex(session_dir=session_dir, project_name=project_name, command="theft", command_args=args.function)

def main():
    parser = argparse.ArgumentParser(description="Robot Army For Good CLI")
    subparsers = parser.add_subparsers(dest="command")
    test_parser = subparsers.add_parser("test", help="Generate and run tests for given project and function")
    # test_parser.add_argument("project", type=str, help="The GitHub project to test ('owner/repo')")
    test_parser.add_argument("codex_session_id", type=str, help="The Codex session ID to clone")
    test_parser.add_argument("function", type=str, help="The function to test ('path/to/file.c:function_name')")
    test_parser.set_defaults(func=run_test)

    build_parser = subparsers.add_parser("build", help="Build tests for a given project")
    build_parser.add_argument("project", type=str, help="The GitHub project to build ('owner/repo')")
    build_parser.set_defaults(func=run_build)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()