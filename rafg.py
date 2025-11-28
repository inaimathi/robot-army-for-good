import argparse
import os
from uuid import uuid4
import subprocess
import datetime

def gen_session_id() -> str:
    # return the date and time with a few random characters appended
    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    random_str = uuid4().hex[:6]
    return f"{date_str}_{random_str}"

def github_clone(session_id: str, project: str, project_dir: str):
    print(f"Cloning GitHub project: {project}")
    os.makedirs(session_id, exist_ok=False)

    subprocess.run(["git", "clone", f"https://github.com/{project}.git", f"{session_id}/{project_dir}"], check=True)

def run_codex(session_id: str, project_dir: str, function_name: str, command: str = "theft"):
    print(f"Running Codex on project directory: {session_id}/{project_dir}\n  command: /{command} {function_name}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, f"commands/{command}.md"), "r") as f:
        command_description = f.read()

    command_description = command_description.replace("$ARGUMENTS", function_name)

    subprocess.run(["codex",
                        "--ask-for-approval", "never",
                        "exec",
                        "--sandbox", "workspace-write",
                        "-"
                    ], cwd=f"{session_id}/{project_dir}", check=True, input=command_description.encode("utf-8"))

def run_test(args):
    session_id = gen_session_id()
    print("Session ID:", session_id)

    project = args.project
    function = args.function
    project_dir = project.split("/")[-1]
    print(f"Generating and running tests for project: {project}, function: {function}")
    github_clone(session_id, project, project_dir)
    run_codex(session_id, project_dir, function)

def main():
    parser = argparse.ArgumentParser(description="Robot Army For Good CLI")
    subparsers = parser.add_subparsers(dest="command")
    test_parser = subparsers.add_parser("test", help="Generate and run tests for given project and function")
    test_parser.add_argument("project", type=str, help="The GitHub project to test ('owner/repo')")
    test_parser.add_argument("function", type=str, help="The function to test ('path/to/file.c:function_name')")
    test_parser.set_defaults(func=run_test)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()