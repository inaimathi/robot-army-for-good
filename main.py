import argparse

from rafg.catalog import catalog_new, catalog_build, catalog_test

def run_build(args) -> None:
    catalog_new(args.project)
    catalog_build(args.project)

def run_test(args) -> None:
    catalog_test(args.project, args.function)

def main():
    parser = argparse.ArgumentParser(description="Robot Army For Good CLI")
    subparsers = parser.add_subparsers(dest="command")
    test_parser = subparsers.add_parser("test", help="Generate and run tests for given project and function")
    test_parser.add_argument("project", type=str, help="The GitHub project to test ('owner/repo')")
    test_parser.add_argument("function", type=str, help="The function to test ('path/to/file.c:function_name')")
    test_parser.set_defaults(func=run_test)

    build_parser = subparsers.add_parser("build", help="Build tests for a given project")
    build_parser.add_argument("project", type=str, help="The GitHub project to build ('owner/repo')")
    build_parser.set_defaults(func=run_build)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()