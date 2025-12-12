import json
import os.path
import subprocess
import sys
from os import environ as ENV
from pathlib import Path
from string import Template
from typing import Any

from trivialai import bedrock, ollama, util
from trivialai.agent import toolbox, toolkit
from trivialai.agent.core import Agent
from trivialai.bistream import force, repeat_until

from . import prepare

# LLM = ollama.Ollama("deepseek-r1:1.5b", "http://localhost:11434/")
# LLM = ollama.Ollama("qwq:latest", "http://localhost:11435/")
LLM = bedrock.Bedrock(
    model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    region="us-east-1",
    aws_access_key_id=ENV["AWS_ACCESS_KEY"],
    aws_secret_access_key=ENV["AWS_ACCESS_SECRET"],
    max_tokens=8192,
)


def main():
    gen = run_pdb_test(str(Path("~/projects/pycronado/").expanduser().resolve()))
    return force(gen)


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
        python = os.path.join(repo_root, "venv-robot_army", "bin", "python")
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


def run_pdb_test(path: str):
    repo_root = path
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
        name="pdb_agent_008",
    )

    def report_path(src_file_path):
        rel = str(Path(src_file_path).relative_to(Path(repo_root)))
        return agent.filepath(f"report_{rel.replace('/', '_')}.md")

    def _check_resp(resp: str) -> dict[str, Any]:
        """
        Parse a model response into a multi-object envelope:

            {
              "type": "multi",
              "items": [ {...}, {...}, ... ]
            }

        Each item must be a dict with type in {"summary", "conclusion", "tool-call"}.
        Tool-calls are passed through agent.check_tool for validation.
        """
        objs = util.loadchmulti(resp)

        items: list[dict[str, Any]] = []
        for obj in objs:
            if not isinstance(obj, dict):
                raise util.TransformError("invalid-object-structure")

            ptype = obj.get("type")
            if ptype not in {"summary", "conclusion", "tool-call"}:
                raise util.TransformError("invalid-object-structure")

            if ptype == "tool-call":
                items.append(agent.check_tool(obj))
            else:
                items.append(obj)

        return {"type": "multi", "items": items}

    def _per_file_stream(f: str):
        tool_calls: list[tuple[dict[str, Any], Any]] = []
        test_results: dict[str, Any] | None = None
        summaries: list[str] = []

        prompt = Template(util.slurp("resources/pdb_file_prompt.md")).safe_substitute(
            repo_path=path,
            files=files,
            file_path=f,
            tool_shape=agent.tool_shape(),
        )

        base = agent.stream_checked(_check_resp, prompt)

        def handle_tool_call(parsed: dict[str, Any]):
            nonlocal test_results

            res = agent.call_tool(parsed)

            if parsed.get("tool") == "run_repo_tests":
                test_results = res
            else:
                tool_calls.append((parsed, res))

            agent.log(
                {
                    "type": "trivialai.agent.log",
                    "message": f"Running a tool call {parsed} -> {type(res)}",
                }
            )

        def handle_summary(ev):
            summary_text = ev.get("summary") or ""
            if summary_text:
                util.spit(agent.filepath("summaries.md"), summary_text, mode="a")
                util.spit(agent.filepath("summaries.md"), "\n - - -\n\n", mode="a")
            summaries.append(summary_text)

        def handle_conclusion(ev):
            util.spit(report_path(f), ev["summary"])
            return True

        def _proceed(final_ev: dict[str, Any]):
            nonlocal test_results

            parsed = final_ev.get("parsed") or {}
            # Backwards-compat: if parsed is not our "multi" envelope,
            # treat it as a single-item list.
            if parsed.get("type") == "multi" and "items" in parsed:
                items: list[dict[str, Any]] = parsed["items"] or []
            else:
                # Single-object path (older agents / tests)
                items = [parsed] if isinstance(parsed, dict) else []

            if not items:
                # Nothing to do; let repeat_until drive another iteration.
                return

            # Process everything in order.
            saw_conclusion = any(it.get("type") == "conclusion" for it in items)

            # First: handle all tool calls
            for it in items:
                if it.get("type") == "summary":
                    handle_summary(it)
                if it.get("type") == "tool-call":
                    handle_tool_call(it)
                if it.get("type") == "conclusion":
                    util.spit(report_path(f), json.dumps(it))

            # If we saw a conclusion, we *do not* schedule another LLM pass.
            # repeat_until(stop=...) will see this and end the loop.
            if saw_conclusion:
                return

            # Otherwise, craft a follow-up prompt that reflects
            # all current tool_calls, summaries, and latest test results.
            calls_txt = "\n\n".join(
                f"You previously asked me to run the tool call {pc}. "
                f"The result of that call was:\n```json\n{r}\n```"
                for pc, r in tool_calls
            )

            tests_txt = (
                "The most recent test run result is:\n" f"```json\n{test_results}\n```"
                if test_results is not None
                else "You have not run the repository tests yet for this file."
            )

            if summaries:
                journal_txt = "\n\n---\n\n".join(
                    f"Summary {i+1}:\n{txt}" for i, txt in enumerate(summaries)
                )
                summaries_section = (
                    f"So far, you have recorded the following progress summaries "
                    f"for {f}:\n\n{journal_txt}\n\n"
                )
            else:
                summaries_section = (
                    f"You have not yet provided any progress summaries for {f}.\n\n"
                )

            guidance = (
                "Use the test results (if any), your previous tool calls, and your current\n"
                "understanding to either:\n"
                "- write or refine more property-based tests, or\n"
                "- identify and explain concrete bugs, or\n"
                "- when you are genuinely finished with this file, respond with a JSON\n"
                "  object of the form:\n"
                '    {"type": "conclusion", "summary": MarkdownString}\n\n'
            )

            pr = (
                f"{summaries_section}"
                f"{tests_txt}\n\n"
                f"{calls_txt}\n\n"
                f"{guidance}"
                f"{prompt}\n"
            )

            # Schedule exactly one more LLM pass with the updated prompt.
            yield from agent.stream_checked(_check_resp, pr)

        # Repeatedly run LLM -> tools -> LLM until we see a conclusion in parsed["items"].
        return repeat_until(
            base,
            _proceed,
            pred=lambda ev: isinstance(ev, dict) and ev.get("type") == "final",
            stop=lambda final_ev, i: any(
                (it.get("type") == "conclusion")
                for it in (
                    (final_ev.get("parsed") or {}).get("items", [])
                    if (final_ev.get("parsed") or {}).get("type") == "multi"
                    else [final_ev.get("parsed") or {}]
                )
            ),
            max_iters=15,
        )

    # Top-level: flatten per-file streams
    for f in src_files[0:2]:
        yield from _per_file_stream(f)
