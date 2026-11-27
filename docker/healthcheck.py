"""Check both the HTTP service and its connection to the detection framework."""

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    try:
        with urlopen("http://127.0.0.1:8000/api/health", timeout=5) as response:
            status = json.load(response)
        return 0 if status.get("status") == "ok" and status.get("framework_available") is True else 1
    except (URLError, TimeoutError, OSError, ValueError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
