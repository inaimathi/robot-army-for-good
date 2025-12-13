# pdb_runner.py
import json
import os.path
import subprocess
import time
from os import environ as ENV
from pathlib import Path
from string import Template
from typing import Any

from trivialai import bedrock, util
from trivialai.agent import toolbox
from trivialai.agent.core import Agent
from trivialai.bistream import BiStream, force, isType, repeat_until
from trivialai.log import getLogger

logger = getLogger("robot_army.pdb")

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
        python = os.path.join(repo_root, "env-robot_army", "bin", "python")
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

    def check_resp(self, resp: str) -> list[dict[str, Any]]:
        """
        Parse a model response into a list of items.

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

    def spit_summary(self, text: str) -> None:
        delimiter = "\n - - -\n\n"
        util.spit(self.filepath("summaries.md"), text, mode="a")
        util.spit(self.filepath("summaries.md"), delimiter, mode="a")

    def spit_report(self, origin_path: str, report: str, shrunk: bool = False) -> None:
        rel = str(Path(origin_path).relative_to(Path(self.repo_root)))
        path = self.filepath(
            f"report_{rel.replace('/', '_')}{'_shrunk' if shrunk else''}.md"
        )
        util.spit(path, report)

    def _streamed(self, prompt: str):
        for ev in self.stream_checked(self.check_resp, prompt):
            if (
                isinstance(ev, dict)
                and ev.get("ok")
                and isinstance(ev.get("parsed"), list)
            ):
                parsed = ev["parsed"]
                if all(
                    isinstance(el, dict) and el.get("type") is not None for el in parsed
                ):
                    yield from parsed
                else:
                    raise util.TransformError("invalid-parsed-structure")
            yield ev

    def streamed(self, prompt):
        return BiStream(self._streamed(prompt))


def run_pdb_test(path: str):
    repo_root = path
    files = toolbox.code_ls(path)
    src_files = [f for f in files if f.endswith(".py")]
    reports: list[str] = []

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
        name="pdb_agent_019",
    )

    def _per_file_stream(f: str):
        started = time.time()
        tool_calls: list[tuple[dict[str, Any], Any]] = []
        test_results: dict[str, Any] | None = None
        summaries: list[str] = []
        file_report: str | None = None
        shrunk_report: str | None = None
        error: dict[str, str] | None = None
        exc: BaseException | None = None

        prompt = Template(util.slurp("resources/pdb_file_prompt.md")).safe_substitute(
            repo_path=path,
            files=files,
            file_path=f,
            tool_shape=agent.tool_shape(),
        )

        # --- handlers (pure side-effects) ---

        def handle_tool_call(ev: dict[str, Any]) -> None:
            nonlocal test_results
            res = agent.call_tool(ev)

            if ev.get("tool") == "run_repo_tests":
                test_results = res
            else:
                tool_calls.append((ev, res))

            agent.log(
                {
                    "type": "trivialai.agent.log",
                    "message": f"Running a tool call {ev} -> {type(res)}",
                }
            )

        def handle_summary(ev: dict[str, Any]) -> None:
            txt = ev.get("summary") or ""
            if txt:
                agent.spit_summary(txt)
            summaries.append(txt)

        def handle_conclusion(ev: dict[str, Any]) -> None:
            nonlocal file_report
            rep = ev.get("summary") or ev.get("report") or ""
            file_report = rep
            reports.append(rep)
            agent.spit_report(f, rep)

        def handle_shrunk(ev: dict[str, Any]) -> None:
            nonlocal shrunk_report
            rep = ev.get("summary") or ev.get("report") or ""
            shrunk_report = rep
            agent.spit_report(f, rep, shrunk=True)

        # --- prompt builder for follow-ups (uses accumulated state) ---

        def build_followup_prompt() -> str:
            calls_txt = "\n\n".join(
                f"You previously asked me to run the tool call {pc}. "
                f"The result of that call was:\n```\n{r}\n```"
                for pc, r in tool_calls
            )

            tests_txt = (
                "The most recent test run result is:\n" f"```\n{test_results}\n```"
                if test_results is not None
                else "You have not run the repository tests yet for this file."
            )

            if summaries:
                journal_txt = "\n\n---\n\n".join(
                    f"Summary {i+1}:\n{txt}" for i, txt in enumerate(summaries) if txt
                )
                summaries_section = (
                    f"So far, you have recorded the following progress summaries for {f}:\n\n"
                    f"{journal_txt}\n\n"
                )
            else:
                summaries_section = (
                    f"You have not yet provided any progress summaries for {f}.\n\n"
                )

            return (
                f"{summaries_section}"
                f"{tests_txt}\n\n"
                f"{calls_txt}\n\n"
                f"{prompt}\n"
            )

        base = agent.streamed(prompt)

        try:
            # Stream everything, but side-effect state via taps.
            yield from (
                repeat_until(
                    base,
                    lambda _: agent.streamed(build_followup_prompt()),
                    stop=isType("conclusion"),
                    max_iters=15,
                )
                .tap(handle_tool_call, focus=isType("tool-call"))
                .tap(handle_summary, focus=isType("summary"))
                .tap(handle_conclusion, focus=isType("conclusion"))
            )

            # Optional: shrink report after conclusion (only if we got one).
            if file_report:
                shrink_prompt = Template(
                    util.slurp("resources/pdb_shrinker_prompt.md")
                ).safe_substitute(
                    repo_path=path,
                    files=files,
                    file_path=f,
                    tool_shape=agent.tool_shape(),
                    file_report=file_report,
                )

                # If shrinker emits a conclusion, we treat it as the new report.
                yield from agent.streamed(shrink_prompt).tap(
                    handle_shrunk, focus=isType("conclusion")
                )

        except Exception as e:
            exc = e
            error = {"type": type(e).__name__, "message": str(e)}

        elapsed_s = round(time.time() - started, 3)
        yield {
            "type": "checkpoint",
            "stage": "file",
            "file_path": f,
            "file_report": file_report,
            "shrunk_report": shrunk_report,
            "tests": test_results,
            "error": error,
            "elapsed_s": elapsed_s,
        }

        if exc is not None:
            raise exc

    for f in src_files[0:10]:
        yield from _per_file_stream(f)
