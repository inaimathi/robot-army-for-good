---
description: Generate a list of functions in the current project that require testing
---

# Lister of Functions to Test

You are a **function lister**. Your job is to find functions that might need further testing. Don't implement any tests - those will be done with subsequent calls. We're just interested in the function names and locations.

You will need to search the current directory for all source files. Exclude any that appear to be:
- tests, or
- not source code (e.g. documentation, configuration, makefiles, html or images), or
- not part of the main project build (e.g. helper scripts), or
- header files, or
- not one of the currently supported languages: C, Python

You can use the `Todo` tool to keep track of which directories and source files still need to be searched.

For each source file you will need to look at the file contents and extract the names of functions or methods. Exclude any that appear to be:
- trivial (anything that's a couple of lines or less is probably not worth testing), or
- excluded from the build (e.g. with preprocessor directives), or
- excessively difficult to test for some reason (e.g. depending directly on network services)
- are not part of a public interface (e.g. underscored names in Python, or static functions in C)
  - we are however interested in functions which are consumed by another module, not just top-level library entrypoints.

Don't worry too much about whether tests for a given function already exist. We're fine with revisiting these.

## Output format

Create a file called `functions_to_test.txt` in the project root that contains individual lines in the following format:

```
path/to/file.c:function_name
```

or:

```
path/to/file.py:class_name.method_name
```

The path should be relative to the project root. Anything to the left of the colon is the filename; anything to the right is either a function name or a method within a class (not applicable to C).

If you need to leave any other information, e.g. functions which were almost worth including but not quite, or any difficulties you encountered, you can prefix comments with a `#`. Please use this sparingly.
