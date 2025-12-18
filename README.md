# Robot Army For Good

![Robot Army For Good cover](cover.png)

> A swarm of automated bug-hunting agents, unleashed **for good** on the open-source ecosystem.

---

TODO

1. set up repo
2. for each file, do the testing/gathering routine
3. once the routine is done, read all the reports and summarize them into a final report.
4. second guess all found bugs, recommend the ones you remain confident about
5. for each bug, find the minimum reproducing case

## What is this?

**Robot Army For Good** is an experiment in scaling up automated bug-hunting.

Inspired by research on agentic program analysis and automatic test generation (see [this paper](https://arxiv.org/pdf/2510.09907)), this project aims to:

- spin up **LLM-powered agents** that can read code, docs, and tests
- automatically **propose new tests** to expand coverage
- uncover **lingering bugs** in open-source infrastructure
- emit **repro steps, patches, and issue templates** suitable for maintainers

Think of it as a friendly botnet of reviewers, always on call, always trying to break things — and then fix them.

---

## Project goals

1. **Increase test coverage**  
   - Automatically generate property-based, fuzz, and regression tests.
   - Prioritize high-risk code paths and critical infrastructure projects.

2. **Find real bugs, not just noise**  
   - Focus on actionable findings with clear reproduction steps.
   - Include suggested fixes or at least hypotheses.

3. **Be a good open-source citizen**  
   - Follow project contribution guidelines.
   - Respect rate limits and community norms.
   - Prefer opt-in and transparent reporting.

---

## Status

🚧 **Early days / pre-alpha.**  
Right now this repo mainly contains scaffolding and design notes. Expect rapid, breaking changes.

---

## Getting started

Until there’s a real release, the rough plan is:

```bash
$ git clone https://github.com/<your-username>/robot-army-for-good.git
$ cd robot-army-for-good
$ python3 -m venv env-robots ; source env-robots/bin/activate
env-robots $ python

>>> from src.robot_army import pdb
>>> pdb.main("~/path/to/target/repo")
2025-12-18 15:19:41,919 - robot_army.pbt - INFO - Running on ~/path/to/target/repo...
2025-12-18 15:19:41,920 - robot_army.prepare - INFO - Preparing repository at /abs/path/to/target/repo
2025-12-18 15:19:41,922 - robot_army.prepare - INFO - Wrote plan: /abs/path/to/target/repo/.robot_army/plan.json (kind=node, plan_hash=2b5d349a0c76cf62)
2025-12-18 15:19:41,922 - robot_army.prepare - INFO - Prepare skip (already ok): os_deps.check
2025-12-18 15:19:41,922 - robot_army.prepare - INFO - Prepare skip (already ok): prepare.0
2025-12-18 15:19:41,923 - robot_army.prepare - INFO - Repository preparation complete.
2025-12-18 15:19:41,923 - robot_army.pbt - INFO -    Repo prepared ~/path/to/target/repo...
2025-12-18 15:19:41,929 - robot_army.pbt - INFO - Running test. Full source is 141 files...
2025-12-18 15:19:52,125 - robot_army.pbt - INFO - Identified 13 candidate files...
{'type': 'start', 'provider': 'bedrock', 'model': 'us.anthropic.claude-3-5-sonnet-20241022-v2:0'}
Saying: {"type": "tool-call", "tool": "slurp", "args": {"file_path": "/abs/path/to/target/repo/file.js"}}
...
```

This'll run for a while. At the end, there should be an `./agent-repo` folder containing a `repo-report.md` along with a number of individual file reports. There may or may not also be source code changes and new files in the `target/repo`.
