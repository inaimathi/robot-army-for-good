You are doing the **post-pass shrinker** for a bug-hunting agent run.

Repository: $repo_path  
File under review: $file_path  
Repo file tree (partial): $files

You have an existing report from the previous iterative pass:

--- BEGIN PRIOR REPORT ---
$file_report
--- END PRIOR REPORT ---

## Your task

Using ONLY the information in the prior report (and any tool outputs, tests, or evidence already included inside it), produce a **final, minimal, high-signal** assessment that answers:

1. **Real bug or not?**  
   For each issue mentioned in the prior report, determine whether it is:
   - **REAL**: likely a true bug in the implementation (or a spec/contract violation)
   - **NOT A BUG**: expected behavior / incorrect assumption by the agent
   - **UNCLEAR**: insufficient evidence; needs verification

   You must justify the classification using evidence present in the prior report (e.g., failing assertions, observed outputs, code excerpts already quoted there, etc.). Do not invent facts.

2. **Security/performance impact and priority**  
   For each issue that is REAL or UNCLEAR, classify priority:
   - **HIGH** if it plausibly enables a security issue (auth bypass, data exposure, injection, privilege escalation, unsafe deserialization, etc.) OR a practical DoS/resource exhaustion/perf degradation path an attacker could trigger.
   - **LOW** otherwise.

   If you are not confident it is exploitable, say so and keep it LOW or UNCLEAR-with-LOW by default. Be conservative.

3. **Minimal repro steps**  
   Provide the **smallest repro** you can:
   - Prefer a **single focused test case** (e.g., `pytest` / `unittest` / Hypothesis if appropriate), or
   - A **small REPL-able snippet** that a maintainer can paste and run.

   The repro must target the implementation behavior (not “the agent thinks…”). If the repro depends on environment, state the dependency.

4. **Maintainer-ready bug report**  
   Write a concise bug report a maintainer could accept:
   - Title
   - Affected area (module/file/function if known)
   - Steps to reproduce (link to your minimal repro snippet)
   - Expected vs actual behavior
   - Impact (including priority reasoning)
   - Suggested fix direction (brief; do not over-prescribe)
   - Workaround (if any)

## Constraints

- **Do not call any tools** in this step. (No file reads, no writes, no test runs.)
- **Do not add new issues** that were not in the prior report.
- If the prior report contains multiple suspected issues that are actually the same root cause, merge them and say so.
- If the prior report lacks enough evidence, explicitly say what is missing (e.g., “need exact stack trace”, “need failing test output”, “need contract/spec reference”).

## Required output format

Return EXACTLY one JSON object and nothing else:

```json
{"type": "conclusion", "summary": "MarkdownString"}
````

The `summary` MarkdownString must use this structure:

* `## Verdict`

  * A bullet list of issues with labels: REAL / NOT A BUG / UNCLEAR
* `## Priority`

  * For each REAL/UNCLEAR issue: HIGH or LOW, with a 1–2 sentence justification
* `## Minimal Repros`

  * One subsection per issue, with a fenced code block
* `## Maintainer Bug Report(s)`

  * One compact report per REAL issue (and optionally for UNCLEAR if it’s important)

Keep it tight. Prefer clarity and reproducibility over volume.
