"""Run every mock case in cases.txt through rules.py and print PASS or FAIL."""

import re
import sys
from dataclasses import dataclass

import settings
from rules import load_lists, outcome

_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


@dataclass(frozen=True)
class Case:
    """One file path under the shared folder and the result the requirements expect."""

    case_id: str
    path: str
    expected: str


def full_path(text: str) -> str:
    """Path under the mock shared folder, with backslash-u escapes decoded."""
    decoded = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)
    return f"{settings.MOCK_SHARED_FOLDER}/{decoded}"


def load_cases() -> tuple[dict[str, str], list[Case]]:
    """Linked folders (full path to connection) and the cases, from cases.txt."""
    links: dict[str, str] = {}
    cases: list[Case] = []
    for raw in settings.CASES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("link:"):
            folder, _, connection = line.removeprefix("link:").partition("=")
            links[full_path(folder.strip())] = connection.strip()
        else:
            case_id, path, expected = (part.strip() for part in raw.split("|"))
            cases.append(Case(case_id, full_path(path), expected))
    return links, cases


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    lists = load_lists(settings.LISTS_FILE)
    links, cases = load_cases()
    failed = 0
    for case in cases:
        got = outcome(case.path, links, lists, settings.MAX_DEPTH)
        note = "" if got == case.expected else f"   expected: {case.expected}"
        failed += bool(note)
        print(f"{'FAIL' if note else 'PASS'}  {case.case_id:<7} {case.path}  ->  {got}{note}")
    print(f"\n{len(cases) - failed} of {len(cases)} cases pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
