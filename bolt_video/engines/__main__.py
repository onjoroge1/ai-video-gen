"""Provider-free tools: python -m bolt_video.engines --help."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from pydantic import ValidationError
from .catalog import list_capabilities
from .storyboard import Storyboard, import_vimax, review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["catalog", "validate", "import-vimax"])
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "catalog":
            result = {"capabilities": list_capabilities()}
        else:
            if args.input is None:
                parser.error("this command requires an input JSON file")
            if args.input.stat().st_size > 1024 * 1024:
                raise ValueError("JSON input exceeds 1 MiB")
            data = json.loads(args.input.read_text())
            result = import_vimax(data) if args.command == "import-vimax" else review(Storyboard.model_validate(data))
        text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            # Never overwrite an approved or pre-existing job artifact implicitly.
            with args.output.open("x") as output:
                output.write(text)
        else:
            print(text, end="")
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Plan rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
