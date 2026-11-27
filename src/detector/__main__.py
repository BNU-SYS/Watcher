"""Allow python -m detector to invoke the command-line tool."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
