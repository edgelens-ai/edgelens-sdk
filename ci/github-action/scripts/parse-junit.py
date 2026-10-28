#!/usr/bin/env python3
"""Parse a JUnit XML file and print "<tests> <failures> <errors> <skipped>".

Used by action.yml to compute the summary table.

Handles both shapes:
- root <testsuites> with multiple <testsuite> children
- a single root <testsuite>

For both, totals are summed across every <testsuite> found. Missing
attributes default to 0.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse(path: Path) -> tuple[int, int, int, int]:
    root = ET.parse(path).getroot()
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = root.findall("testsuite") or [root]

    def s(name: str) -> int:
        return sum(int(x.get(name, "0") or "0") for x in suites)

    return s("tests"), s("failures"), s("errors"), s("skipped")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: parse-junit.py PATH", file=sys.stderr)
        return 2
    try:
        tests, failures, errors, skipped = parse(Path(argv[1]))
    except (FileNotFoundError, ET.ParseError) as e:
        print(f"parse-junit: {e}", file=sys.stderr)
        return 1
    print(f"{tests} {failures} {errors} {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
