# Robot Army For Good

![Robot Army For Good cover](cover.png)

> A swarm of automated bug-hunting agents, unleashed **for good** on the open-source ecosystem.

---

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
git clone https://github.com/<your-username>/robot-army-for-good.git
cd robot-army-for-good

# TODO: install CLI / run first agent
