Find bugs in the repository $repo_path. The relevant file tree in the repo is $files.
You are currently working on file $file_path.

For this file, you should work in an iterative loop:

  1. Read the implementation and any existing tests using the available tools.
  2. Propose and write additional tests (for Python: property-based tests with Hypothesis)
     into appropriate test files. IMPORTANT: Do not propose tests that contain sleep calls (the tests will be run with a 300 second timeout, and introducing any sleeps might cause that guard rail to trip)
  3. When you have written or modified tests, call the repository test-running tool
     (for example `run_repo_tests`) to execute the test suite.
  4. Read and analyze the test results. Use them to refine your understanding, fix or
     improve your tests, and identify true bugs in the implementation.
  5. Repeat steps 1–4 until you are reasonably satisfied that you have explored the
     most important bug risks in this file.

Your responses MUST always be one of the following JSON objects:

  1. A tool call. In this case your response MUST be ONLY a single tool-call JSON object
     matching the tool-calling shape shown below (and nothing else):

     $tool_shape
	 
	 Note that your context window is limited, so you can't _really_ write files of arbitrary
	 sizes. If you need to use the `spit` tool to write a large file, call it multiple times
	 with the `"mode"` argument set to `"a"` in order to append.

  2. An intermediate summary of your progress so far for this file, when you want to
     document what you have done but CONTINUE working after this step. In this case your
     response MUST be ONLY:

        {"type": "summary", "summary": MarkdownString}

     The MarkdownString should briefly describe what you have done so far on this file
     (files read, tests written, test runs and their results, suspected issues).

  3. A final conclusion for this file, when you are truly finished and it is appropriate
     to move on to the next file. In this case your response MUST be ONLY:

        {"type": "conclusion", "summary": MarkdownString}

     The MarkdownString should be a concise but complete summary of your findings for this
     file: what you tested, what passed/failed, which bugs you believe are real, and any
     suggested fixes.

You SHOULD NOT emit a `"conclusion"` until you have:

  - written or updated tests where appropriate,
  - (for non-trivial files) run the repository tests at least once using the test-running tool,
  - analyzed the results, and
  - used at least one `"summary"` to reflect on your progress if the situation is complex.
