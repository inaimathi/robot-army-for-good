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
from trivialai.log import getLogger

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

logger = getLogger("robot_army.pdb")


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


class PDBAgent(Agent):
    def __init__(self, llm, repo_root, *args, **kwargs):
        super().__init__(llm, *args, **kwargs)
        self.repo_root = repo_root

    def check_resp(self, resp: str) -> dict[str, Any]:
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
                items.append(self.check_tool(obj))
            else:
                items.append(obj)

        return items

    def spit_summary(self, text):
        delimiter = "\n - - -\n\n"
        util.spit(self.filepath("summaries.md"), text, mode="a")
        util.spit(self.filepath("summaries.md"), delimiter, mode="a")

    def spit_report(self, origin_path, report):
        rel = str(Path(origin_path).relative_to(Path(self.repo_root)))
        path = self.filepath(f"report_{rel.replace('/', '_')}.md")
        util.spit(path, report)

    def streamed(self, prompt):
        return self.stream_checked(self.check_resp, prompt)


def run_pdb_test(path: str):
    repo_root = path
    files = toolbox.code_ls(path)
    src_files = [f for f in files if f.endswith(".py")]
    reports = []

    system = util.slurp("resources/pdb_prompt.md")
    agent = PDBAgent(
        LLM,
        repo_root,
        system=system,
        tools=[
            toolbox.slurp,
            toolbox.spit,
            make_run_repo_tests_tool(repo_root),
        ],
        name="pdb_agent_012",
    )

    def _per_file_stream(f: str):
        tool_calls: list[tuple[dict[str, Any], Any]] = []
        test_results: dict[str, Any] | None = None
        summaries: list[str] = []
        file_report = None

        prompt = Template(util.slurp("resources/pdb_file_prompt.md")).safe_substitute(
            repo_path=path,
            files=files,
            file_path=f,
            tool_shape=agent.tool_shape(),
        )

        base = agent.streamed(prompt)

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
                agent.spit_summary(summary_text)
            summaries.append(summary_text)

        def handle_report(ev):
            nonlocal file_report
            file_report = ev.get("summary") or ev.get("report")
            reports.append(file_report)
            agent.spit_report(f, file_report)

        def _proceed(final_ev: dict[str, Any]):
            nonlocal test_results

            parsed = final_ev.get("parsed") or []
            if not parsed:
                return

            for it in parsed:
                tp = it.get("type")
                if tp == "summary":
                    handle_summary(it)
                if tp == "tool-call":
                    handle_tool_call(it)

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

            pr = (
                f"{summaries_section}"
                f"{tests_txt}\n\n"
                f"{calls_txt}\n\n"
                f"{prompt}\n"
            )

            yield from agent.streamed(pr)

        yield from repeat_until(
            base,
            _proceed,
            pred=isType("final"),
            stop=lambda final_ev, i: any(
                (it.get("type") == "conclusion") for it in final_ev.get("parsed") or []
            ),
            max_iters=15,
        ).tap(
            lambda ev: handle_report(
                [e for e in ev.get("parsed", {}) if e.get("type") == "conclusion"][0]
            ),
            focus=lambda ev: any(
                (it.get("type") == "conclusion") for it in ev.get("parsed") or []
            ),
        )

        yield from agent.streamed(
            Template(util.slurp("resources/pdb_shrinker_prompt.md")).safe_substitute(
                repo_path=path,
                files=files,
                file_path=f,
                tool_shape=agent.tool_shape(),
                file_report=file_report,
            )
        )

    # Top-level: flatten per-file streams
    for f in src_files[0:2]:
        yield from _per_file_stream(f)


def isType(type_name):
    return lambda ev: isinstance(ev, dict) and ev.get("type") == type_name
