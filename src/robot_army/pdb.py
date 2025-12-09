import subprocess
from os import environ as ENV
from pathlib import Path
from string import Template
from typing import Any

from trivialai import bedrock, ollama, util
from trivialai.agent import toolbox, toolkit
from trivialai.agent.core import Agent
from trivialai.bistream import force, repeat_until

# LLM = ollama.Ollama("deepseek-r1:1.5b", "http://localhost:11434/")
# LLM = ollama.Ollama("qwq:latest", "http://localhost:11435/")
LLM = bedrock.Bedrock(
    model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    region="us-east-1",
    aws_access_key_id=ENV["AWS_ACCESS_KEY"],
    aws_secret_access_key=ENV["AWS_ACCESS_SECRET"],
)


def make_run_repo_tests_tool(repo_root: str):
    def run_repo_tests():
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
        try:
            proc = subprocess.run(
                ["sh", "unittest.sh"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=300,  # seconds
            )
        except subprocess.TimeoutExpired as e:
            return {
                "status": "timeout",
                "exit_code": None,
                "stdout": e.stdout or "",
                "stderr": (e.stderr or "") + "\n[timeout]",
            }

        def _trim(s: str, limit: int = 8000) -> str:
            if len(s) <= limit:
                return s
            return s[:limit] + "\n...[truncated]..."

        return {
            "status": "ok" if proc.returncode == 0 else "fail",
            "exit_code": proc.returncode,
            "stdout": _trim(proc.stdout),
            "stderr": _trim(proc.stderr),
        }

    run_repo_tests.__name__ = "run_repo_tests"
    run_repo_tests.__doc__ = (
        "Run the repository's unit test suite and return status/stdout/stderr. "
        "Use this after you have written or modified tests."
    )
    return run_repo_tests


def main():
    gen = run_pdb_test(str(Path("~/projects/pycronado/").expanduser().resolve()))
    return force(gen)


def run_pdb_test(path: str):
    files = toolbox.code_ls(path)
    src_files = [f for f in files if f.endswith(".py")]

    system = util.slurp("resources/pdb_prompt.md")
    agent = Agent(
        LLM,
        system=system,
        tools=[
            toolbox.slurp,
            toolbox.spit,
            make_run_repo_tests_tool(path),
        ],
        name="pdb_agent_002",
    )

    def _check_resp(resp: str) -> dict[str, Any]:
        parsed = util.loadch(resp)
        if parsed.get("type") not in {"summary", "conclusion", "tool-call"}:
            raise util.TransformError("invalid-object-structure")
        if parsed["type"] == "tool-call":
            return agent.check_tool(parsed)
        return parsed

    def _per_file_stream(f: str):
        tool_calls = []
        test_results = None
        prompt = Template(util.slurp("resources/pdb_file_prompt.md")).safe_substitute(
            repo_path=path,
            files=files,
            file_path=f,
            tool_shape=agent.tool_shape(),
        )

        base = agent.stream_checked(_check_resp, prompt)

        def _proceed(final_ev: dict[str, Any]):
            parsed = final_ev.get("parsed", {})

            if parsed.get("type") == "tool-call":
                res = agent.call_tool(parsed)
                if parsed.get("tool") == "run_repo_tests":
                    nonlocal test_results
                    test_results = res
                else:
                    tool_calls.append((parsed, res))
                agent.log(
                    {
                        "type": "trivialai.agent.log",
                        "message": f"Running a tool call {parsed} -> {type(res)}",
                    }
                )

                calls = "\n\n".join(
                    [
                        f"You previously asked me to run the tool call {parsed}. THe result of that call was {res}"
                        for parsed, res in tool_calls
                    ]
                )

                tests = (
                    f"The most recent test results are: {test_results}\n"
                    if test_results is not None
                    else ""
                )
                pr = f"{calls}\n{tests}\n{prompt}\n"

                yield from agent.stream_checked(_check_resp, pr)

            # For parsed["type"] == "summary" we don't do anything here.
            # repeat_until will notice the summary and stop scheduling more passes.

        # Repeatedly run LLM -> tool -> LLM until we see a summary in parsed["type"]
        return repeat_until(
            base,
            _proceed,
            pred=lambda ev: isinstance(ev, dict) and ev.get("type") == "final",
            stop=lambda final_ev, i: final_ev.get("parsed", {}).get("type")
            == "conclusion",
            max_iters=10,  # or whatever upper bound you like
        )

    # Top-level: flatten per-file streams
    for f in src_files[0:2]:
        yield from _per_file_stream(f)
