# pdbagent.py
from pathlib import Path
from typing import Any

from trivialai import util
from trivialai.agent.core import Agent
from trivialai.bistream import BiStream

from . import agent_tools


class PDBAgent(Agent):
    def __init__(self, llm, repo_root, *args, **kwargs):
        # Caller does not supply tools; we build them here.
        kwargs.pop("tools", None)

        root = Path(repo_root).expanduser().resolve()

        def write_own_scratchpad(text: str, mode: str = "w") -> dict[str, Any]:
            """
            Write directly to this agent's own scratchpad.

            You only need to provide the text. Optionally provide mode ("w" or "a");
            if omitted, it defaults to overwrite ("w").
            """
            try:
                p = Path(self.filepath("scratchpad.md")).expanduser().resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                util.spit(str(p), text, mode=mode)
                return {
                    "status": "ok",
                    "file_path": str(p),
                    "mode": mode,
                    "bytes": len(text),
                }
            except Exception as e:
                return {
                    "status": "fail",
                    "error": type(e).__name__,
                    "message": str(e),
                    "mode": mode,
                }

        tools = agent_tools.make_tools(root)
        tools.append(write_own_scratchpad)

        super().__init__(llm, *args, tools=tools, **kwargs)
        self.repo_root = str(root)

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
            f"report_{rel.replace('/', '_').replace('.', '_')}{'_shrunk' if shrunk else''}.md"
        )
        util.spit(path, f"# Report for {rel}\n\n")
        util.spit(path, report, mode="a")

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
