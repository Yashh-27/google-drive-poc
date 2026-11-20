"""Folder-name rules from the Drive import requirements (GD-12, GD-20 to GD-26)."""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

IGNORE_LIST = "ignore"
IGNORED = "ignored"
CONFLICT = "conflict"
NO_ENTRY_TYPE = "no entry type"
TOO_DEEP = "too deep"
NOT_LINKED = "not linked"


@dataclass(frozen=True)
class Pattern:
    """One saved folder name; '*' stands for any text (GD-21)."""

    text: str
    entry_type: str
    regex: re.Pattern[str]

    @property
    def is_exact(self) -> bool:
        return "*" not in self.text


@dataclass
class Lists:
    """The organisation's names per entry type, and its ignored names."""

    patterns: list[Pattern] = field(default_factory=list)
    ignored: list[Pattern] = field(default_factory=list)


def normalise(name: str) -> str:
    """Ignore capitals, spaces at either end and how accents are stored (GD-23)."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).strip().casefold())


def compile_pattern(text: str, entry_type: str) -> Pattern:
    """Refuse a name that is empty or only '*', which would match every folder."""
    norm = normalise(text)
    if not norm.replace("*", "").strip():
        raise ValueError(f"lists.txt: {entry_type} has an empty or '*'-only name {text!r}")
    body = ".*".join(re.escape(part) for part in norm.split("*"))
    return Pattern(norm, entry_type, re.compile(body, re.DOTALL))


def load_lists(path: Path) -> Lists:
    """Read lists.txt, refusing a name saved for two entry types or also ignored (GD-26)."""
    lists, owners = Lists(), {}
    for entry_type, names in _rows(path):
        for name in names:
            pattern = compile_pattern(name, entry_type)
            owner = owners.setdefault(pattern.text, entry_type)
            if owner != entry_type:
                raise ValueError(f"lists.txt: {name!r} is on both {owner} and {entry_type}")
            (lists.ignored if entry_type == IGNORE_LIST else lists.patterns).append(pattern)
    return lists


def nearest_link(folders: list[str], links: dict[str, str]) -> tuple[int, str] | None:
    """Index and connection of the nearest linked folder above the file (GD-12)."""
    for end in range(len(folders), 0, -1):
        connection = links.get("/".join(folders[:end]))
        if connection is not None:
            return end - 1, connection
    return None


def classify(folders: list[str], business_index: int, lists: Lists, max_depth: int) -> str:
    """Entry type of a file under folders (shared folder first), or why it has none."""
    if any(_hits(name, lists.ignored) for name in folders):
        return IGNORED
    if len(folders) - business_index - 1 > max_depth:
        return TOO_DEEP
    for name in reversed(folders):
        hits = _hits(name, lists.patterns)
        if hits:
            return _resolve(hits)
    return NO_ENTRY_TYPE


def outcome(path: str, links: dict[str, str], lists: Lists, max_depth: int) -> str:
    """'<result> @ <connection>' for a file path, or 'not linked'."""
    folders = path.split("/")[:-1]
    link = nearest_link(folders, links)
    if link is None:
        return NOT_LINKED
    index, connection = link
    return f"{classify(folders, index, lists, max_depth)} @ {connection}"


def _rows(path: Path) -> list[tuple[str, list[str]]]:
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry_type, sep, names = line.partition(":")
        if not sep:
            raise ValueError(f"lists.txt: no ':' in {raw!r}")
        rows.append((entry_type.strip(), [n.strip() for n in names.split(",") if n.strip()]))
    return rows


def _hits(name: str, patterns: list[Pattern]) -> list[Pattern]:
    norm = normalise(name)
    return [p for p in patterns if p.regex.fullmatch(norm)]


def _resolve(hits: list[Pattern]) -> str:
    """An exact name beats a '*' name (POC choice); two entry types left is a conflict."""
    exact = [p for p in hits if p.is_exact]
    entry_types = {p.entry_type for p in (exact or hits)}
    return entry_types.pop() if len(entry_types) == 1 else CONFLICT
