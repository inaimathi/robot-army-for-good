# pdb.py
import sys
import time
from os import environ as ENV
from pathlib import Path
from string import Template
from types import TracebackType
from typing import Any

from trivialai import bedrock, ollama, util
from trivialai.agent import toolbox
from trivialai.bistream import BiStream, force, isType, repeat_until
from trivialai.log import getLogger

from . import pdbagent, prepare

logger = getLogger("robot_army.pdb")

LLM = bedrock.Bedrock(
    model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    region="us-east-1",
    aws_access_key_id=ENV["AWS_ACCESS_KEY"],
    aws_secret_access_key=ENV["AWS_ACCESS_SECRET"],
    max_tokens=8192,
)
# LLM = ollama.Ollama("qwq-uncapped:latest", "http://localhost:11435/")
# LLM = ollama.Ollama("deepseek-coder-v2:latest", "http://localhost:11435/")

CHECKPOINT = "pdb.checkpoint"


def main():
    checkpoints = []
    gen = BiStream(
        run_pdb_test(str(Path("~/projects/pycronado/").expanduser().resolve()))
    ).tap(lambda ev: checkpoints.append(ev), focus=isType(CHECKPOINT)).then(
        LLM.stream(, json.dumps(checkpoints))
    )
    force(gen)
    print("**************************************************")
    print("SEQUENCE COMPLETE")
    print("**************************************************")
    return LLM.stream
    return checkpoints


def run_pdb_test(path: str):
    repo_root = path
    files = toolbox.code_ls(path)
    src_files = [f for f in files if f.endswith(".py")]
    reports: list[str] = []

    system = util.slurp("resources/pdb_prompt.md")
    agent = pdbagent.PDBAgent(
        LLM,
        repo_root,
        system=system,
        name="pdb_agent_023",
    )

    def _per_file_stream(f: str):
        started = time.time()
        tool_calls: list[tuple[dict[str, Any], Any]] = []
        test_results: dict[str, Any] | None = None
        summaries: list[str] = []
        file_report: str | None = None
        shrunk_report: str | None = None
        error: dict[str, str] | None = None

        exc_info: (
            tuple[type[BaseException], BaseException, TracebackType | None] | None
        ) = None

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
            # Preserve full traceback for the eventual re-raise after emitting checkpoint.
            _t, _e, _tb = sys.exc_info()
            exc_info = (_t, _e, _tb)
            error = {"type": type(e).__name__, "message": str(e)}

        elapsed_s = round(time.time() - started, 3)
        yield {
            "type": CHECKPOINT,
            "stage": "file",
            "file_path": Path(f).relative_to(Path(repo_root)),
            "file_report": file_report,
            "shrunk_report": shrunk_report,
            "tests": test_results,
            "error": error,
            "elapsed_s": elapsed_s,
        }

        if exc_info is not None:
            _t, _e, _tb = exc_info
            raise _e.with_traceback(_tb)

    for f in src_files[0:1]:
        yield from _per_file_stream(f)
