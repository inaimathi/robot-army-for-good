---
description: Build tests for a given C project
---

Your task is to build the **tests** for the current C project.

1. If the language of the project is not **C**, then stop (for these purposes, C++ is not C).
2. If the project does not build a library or executable then stop. (e.g. if it's a tutorial, website, documentation, list of links, etc.)
3. If the environment is missing dev dependencies (libraries or header files) then explain what's missing and then stop. The sandbox will probably prevent you from installing them yourself. If possible, try to obtain a complete list of what's missing rather than just the first library in the list. This will save time.
4. If the environment is missing necessary tooling (compilers, automake, etc.) then explain what's missing and then stop.
5. If the project does not appear to have any **unit tests** then stop. For these purposes, a unit test is any **test** (not part of the main project build) that **directly calls C code from the main project**. Tests that invoke the entire executable do not count as unit tests. If unit tests are missing, explain the situation and stop.
6. Build and run the unit tests.
7. If the build **fails** for a nontrivial or unrecoverable reason, explain the situation and stop.
8. Add a unit test of your own and run it via the build system. The unit test can be trivial, but it should call a function in the main project code.
9. Report if building/running the tests or project is very **slow**.
10. If you get this far, exit successfully.

It is **ok to create files in the current project**. They will be cleaned up separately.
