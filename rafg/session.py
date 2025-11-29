import json
import os
import shutil
import subprocess
from uuid import UUID, uuid4
from datetime import datetime, timezone

def _sessions_root() -> str:
    return os.path.expanduser("~/sessions")

def _kludgy_uuid7() -> UUID:
    """
    Generate a UUIDv7-like string using current timestamp and random bits

    Some versions of python do not support uuid.uuid7(), so we implement our own version here.
    """
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    timestamp_hex = f"{timestamp:012x}"
    random_hex_and_var = uuid4().hex[13:]
    return UUID(timestamp_hex + "7" + random_hex_and_var)

def _github_clone(session_repo_dir: str, org: str, project: str) -> str:
    """
    Clone a GitHub project into the specified session repo directory.
    
    The GitHub project is "{org}/{project}", neither of which should contain slashes.

    We return the session project dir, which will be "{session_repo_dir}/{project}".
    """
    print(f"Cloning GitHub project: {project}")
    os.makedirs(session_repo_dir, exist_ok=True)
    subprocess.run(["git", "clone", f"https://github.com/{org}/{project}.git", f"{session_repo_dir}/{project}"], check=True)
    return f"{session_repo_dir}/{project}"

def _create_codex_rollout(session_dir: str, session_id: str, apparent_project_dir: str, session_project_dir: str) -> None:
    """
    Create a stub Codex rollout in the specified session directory.

    The apparent_project_dir is the directory where the project will be mounted when Codex runs.
    This is not the same as the session project dir.
    """
    if os.path.exists(f"{session_dir}/rollout.jsonl"):
        raise FileExistsError(f"Codex rollout file already exists: {session_dir}/rollout.jsonl")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cwd = os.path.abspath(apparent_project_dir)

    # Get git hash, repository url and branch from the session project dir
    git_commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=session_project_dir).decode("utf-8").strip()
    git_repository_url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=session_project_dir).decode("utf-8").strip()
    git_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=session_project_dir).decode("utf-8").strip()

    line0 = json.dumps({"timestamp": timestamp,"type":"session_meta","payload":{"id":session_id,"timestamp": timestamp,"cwd":cwd,"originator":"codex_exec","cli_version":"0.63.0","instructions":None,"source":"exec","model_provider":"openai","git":{"commit_hash":git_commit_hash,"branch":git_branch,"repository_url":git_repository_url}}})
# This part may or may not be necessary
#     line1 = json.dumps({
#         "timestamp": timestamp, "type":"response_item",
#         "payload":{
#             "type":"message", "role":"user",
#             "content":[{
#                 "type":"input_text",
#                 "text":
# f"""<environment_context>
#   <cwd>{cwd}</cwd>
#   <approval_policy>never</approval_policy>
#   <sandbox_mode>workspace-write</sandbox_mode>
#   <network_access>restricted</network_access>
#   <shell>bash</shell>
# </environment_context>"""}]
#         }})

    with open(f"{session_dir}/rollout.jsonl", "w") as f:
        f.write(f"{line0}\n")

def _datetime_from_session_id(session_id: str) -> datetime:
    """
    Given a session ID, return the datetime when it was created.

    This involves extracting the timestamp from the UUIDv7 session ID.
    """
    u = UUID(session_id)
    timestamp_hex = u.hex[:12]
    timestamp = int(timestamp_hex, 16)
    return datetime.fromtimestamp(timestamp/1000, timezone.utc)

def _codex_session_to_filename(session_id: str) -> str:
    """
    Given a session ID, return the filename where its rollout is stored.

    This involves extracting the timestamp from the UUIDv7 session ID.
    """
    filename = _datetime_from_session_id(session_id).strftime(".codex/sessions/%Y/%m/%d/rollout-%Y-%m-%dT%H-%M-%S")
    filename += f"-{session_id}.jsonl"
    return filename

def _install_codex_rollout(session_dir: str, session_id: str) -> None:
    src_filename = f"{session_dir}/rollout.jsonl"
    if not os.path.exists(src_filename):
        raise FileNotFoundError(f"Codex rollout file not found: {src_filename}")
    dst_filename = _codex_session_to_filename(session_id)
    if os.path.exists(dst_filename):
        raise FileExistsError(f"Codex rollout file already exists: {dst_filename}")
    os.makedirs(os.path.dirname(dst_filename), exist_ok=True)
    shutil.copyfile(src_filename, dst_filename)

def _copy_codex_rollout_back(session_dir: str, session_id: str) -> None:
    src_filename = _codex_session_to_filename(session_id)
    if not os.path.exists(src_filename):
        raise FileNotFoundError(f"Codex rollout file not found: {src_filename}")
    dst_filename = f"{session_dir}/rollout.jsonl"
    shutil.copyfile(src_filename, dst_filename)

def _check_codex_rollout_installed(session_dir: str, session_id: str) -> None:
    codex_filename = _codex_session_to_filename(session_id)
    if not os.path.exists(codex_filename):
        raise FileNotFoundError(f"Codex rollout file not found: {codex_filename}")
    local_filename = f"{session_dir}/rollout.jsonl"
    if not os.path.exists(local_filename):
        raise FileNotFoundError(f"Local rollout file not found: {local_filename}")
    with open(codex_filename, "r") as f_codex, open(local_filename, "r") as f_local:
        codex_text = f_codex.read()
        local_text = f_local.read()
    if codex_text != local_text:
        codex_len = len(codex_text.splitlines())
        local_len = len(local_text.splitlines())
        raise ValueError(f"Codex rollout file does not match local rollout file. They should be identical. Codex file has {codex_len} lines, Local file has {local_len} lines.")

def _tweak_codex_rollout(session_dir: str, old_session_id: str, new_session_id: str) -> None:
    with open(f"{session_dir}/rollout.jsonl", "r") as f:
        text = f.read().replace(old_session_id, new_session_id)
    with open(f"{session_dir}/rollout.jsonl", "w") as f:
        f.write(text)

def session_new(github_project: str) -> str:
    """
    Create a new Robot Army For Good session and return the session ID.

    It will have the given github project cloned into it.

    The session is stored in ~/sessions/{session_id}/ and will also be stored in
    Codex's session storage system (~/.codex/sessions/y/m/d/rollout-...jsonl).
    The same session id is used for both places, and will be a UUIDv7 (that implicitly
    contains a date and time).
    """
    session_id = str(_kludgy_uuid7())
    org, project = github_project.split("/")
    session_dir = f"{_sessions_root()}/{session_id}"
    session_repo_dir = f"{session_dir}/repo"
    session_project_dir = _github_clone(session_repo_dir, org, project)
    home_dir = os.path.expanduser("~")
    apparent_project_dir = f"{home_dir}/repo/{project}"
    _create_codex_rollout(session_dir, session_id, apparent_project_dir, session_project_dir)
    _install_codex_rollout(session_dir, session_id)
    os.makedirs(f"{session_dir}/tmp", exist_ok=True)
    dt = _datetime_from_session_id(session_id)
    with open(f"{session_dir}/config", "w") as f:
        json.dump({
            "timestamp": dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "github_owner": org,
            "github_project": project,
            "session_id": session_id,
            "cwd": apparent_project_dir,
            "parent": None
        }, f, indent=2)
    return session_id

def session_clone(src_session_id: str) -> str:
    """
    Clone an existing Robot Army For Good session and return the new session ID.

    The cloned session will have a new session ID, and its own copy of the project.
    The Codex rollout will be identical except the session ID will be changed.

    The new session is stored in ~/sessions/{new_session_id}/ and will also be stored in
    Codex's session storage system (~/.codex/sessions/y/m/d/rollout-...jsonl).
    """
    src_session_dir = f"{_sessions_root()}/{src_session_id}"
    if not os.path.exists(src_session_dir):
        raise FileNotFoundError(f"Session directory not found: {src_session_dir}")
    if not os.path.exists(f"{src_session_dir}/has_child"):
        with open(f"{src_session_dir}/has_child", "w") as f:
            f.write("true")
    dst_session_id = str(_kludgy_uuid7())
    dst_session_dir = f"sessions/{dst_session_id}"
    shutil.copytree(src_session_dir, dst_session_dir)
    if os.path.exists(f"{dst_session_dir}/has_child"):
        os.remove(f"{dst_session_dir}/has_child")
    _tweak_codex_rollout(dst_session_dir, src_session_id, dst_session_id)
    _install_codex_rollout(dst_session_dir, dst_session_id)

    dt = _datetime_from_session_id(dst_session_id)
    with open(f"{dst_session_dir}/config", "r") as f:
        config = json.load(f)
    config["timestamp"] = dt.isoformat(timespec="seconds").replace("+00:00", "Z")  # the timestamp that matches the session ID. May not correspond to the latest activity for this session.
    config["session_id"] = dst_session_id
    config["parent"] = src_session_id
    with open(f"{dst_session_dir}/config", "w") as f:
        json.dump(config, f, indent=2)

    return dst_session_id

def session_run(session_id: str, instructions: str) -> None:
    """
    Run Codex on the specified Robot Army For Good session.

    The session must already exist both in sessions/{session_id}/ and in
    Codex's session storage system (.codex/sessions/y/m/d/rollout-...jsonl)
    and they must be identical.

    This command will invoke "codex exec resume {session_id}".
    When it's done, it will copy the updated rollout back to sessions/{session_id}/rollout.jsonl
    """
    session_dir = f"{_sessions_root()}/{session_id}"
    if not os.path.exists(session_dir):
        raise FileNotFoundError(f"Session directory not found: {session_dir}")
    if os.path.exists(f"{session_dir}/has_child"):
        raise ValueError(f"Cannot run Codex directly on session that has a child session: {session_id} (clone it first)")
    _check_codex_rollout_installed(session_dir, session_id)

    with open(f"{session_dir}/config", "r") as f:
        config = json.load(f)
        if config["session_id"] != session_id:
            raise ValueError(f"Session ID in config does not match: {config['session_id']} != {session_id}")
    apparent_project_dir = config["cwd"]
    session_project_dir = f"{session_dir}/repo/{config['github_project']}"
    print(f"Running Codex on session: {session_id}")

    with open(f"{session_dir}/cmd", "w") as f:
        f.write(instructions)

    os.makedirs(apparent_project_dir, exist_ok=True)

    bash_cmd = f"""set -ex
mount --bind {session_project_dir} {apparent_project_dir}
cd {apparent_project_dir}
cat {session_dir}/cmd | sudo -u ubuntu codex --ask-for-approval never exec --sandbox workspace-write resume {session_id} -
"""

    try:
        subprocess.run(["sudo","unshare","--mount","bash","-c", bash_cmd], check=True)
    finally:
        print("Copying updated Codex rollout back to session directory")
        _copy_codex_rollout_back(session_dir, session_id)
    
if __name__ == "__main__":
    # check it works
    parent_id = session_new("jqlang/jq")
    print("Created session:", parent_id)
    session_run(parent_id, "Create a file named hello.txt with the content 'Hello, World!'\n")
    child_id = session_clone(parent_id)
    print("Cloned session:", child_id)
    session_run(child_id, "Append the text 'This is a cloned session.' to hello.txt\n")
    print(f"Original session id: {parent_id}. Cloned session id: {child_id}.")