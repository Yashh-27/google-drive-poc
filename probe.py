"""POC commands against Google Drive or the local mock: access, link, new, hash, activity."""

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import PurePath

import settings
from drive import FOLDER, GOOGLE_APPS, SHORTCUT, DriveError, GoogleDrive, LocalDrive, open_source
from rules import CONFLICT, IGNORED, NO_ENTRY_TYPE, Lists, classify, load_lists

Children = Callable[[str], list[dict]]
Drive = GoogleDrive | LocalDrive
NOT_OFFERED = {
    IGNORED: "ignored folder, never offered",
    NO_ENTRY_TYPE: "no entry type, listed only",
    CONFLICT: "two entry types fit, not offered",
}


class Probe:
    """The POC commands over one source, 'google' or 'local'."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.drive: Drive = open_source(source)

    def access(self) -> None:
        """Shared folders and shared drives the address can read (GD-05)."""
        roots = self.drive.shared_roots()
        print(f"{len(roots)} shared folders or drives readable")
        for root in roots:
            print(f"  {root['kind']:<13} {root['name']}  id={root['id']}  owner={_owner(root)}")

    def link(self, ref: str, connection: str, all_new: bool) -> None:
        """Record the folder's current files as existing (GD-40); --all-new records none."""
        folder = resolve(self.drive, ref)
        if folder["mimeType"] != FOLDER:
            raise SystemExit(f"{folder['name']} is not a folder")
        files, _ = walk(self.drive.children, folder["id"], [folder["name"]], None)
        existing = [] if all_new else [item["id"] for item, _ in files]
        links = load_links(self.source)
        links[folder["id"]] = {"connection": connection, "name": folder["name"],
                               "linked_at": _now(), "existing": existing}
        save_links(self.source, links)
        print(f"linked {folder['name']} ({folder['id']}) to {connection}; {len(existing)} existing files recorded")

    def new(self, use_index: bool) -> None:
        """Waiting files per linked folder, listed the way the upload window would show them."""
        links, lists = load_links(self.source), load_lists(settings.LISTS_FILE)
        if not links:
            raise SystemExit("No linked folders yet; run link first.")
        base = children_for(self.drive, use_index)
        for folder_id, link in links.items():
            start, calls = time.perf_counter(), self.drive.calls
            try:
                self._report(without(base, set(links) - {folder_id}), folder_id, link, lists)
            except DriveError as exc:
                print(f"\n{link['connection']}: cannot read {link['name']} any more ({exc})")
            print(f"  {self.drive.calls - calls} API calls, {time.perf_counter() - start:.2f} s")
        if self.drive.incomplete:
            print(f"\nGoogle marked {self.drive.incomplete} listings as incomplete")

    def hash(self, file_id: str) -> None:
        """Download one file and compare its SHA-256 with the one Google reports (GD-55)."""
        item = self.drive.get(file_id)
        try:
            data = self.drive.download(file_id)
        except DriveError as exc:
            print(f"{item['name']}: download refused ({exc})")
            return
        actual, reported = hashlib.sha256(data).hexdigest(), item.get("sha256Checksum")
        verdict = "MATCH" if actual == reported else "DIFFERENT"
        print(f"{item['name']}: {len(data)} bytes; Google {reported}; file {actual}; {verdict}")

    def activity(self, folder_id: str) -> None:
        """Google's record of who created, moved, renamed, binned or restored files (GD-68, GD-70)."""
        events = self.drive.activity(folder_id)
        print(f"{len(events)} events under {folder_id}")
        for event in events:
            when = event.get("timestamp") or event.get("timeRange", {}).get("endTime")
            print(f"  {when}  {_action(event)}  by {_actor(event)}  on {_targets(event)}")

    def _report(self, children: Children, folder_id: str, link: dict, lists: Lists) -> None:
        folder = self.drive.get(folder_id)
        prefix = ancestry(self.drive, folder)
        files, notes = walk(children, folder_id, prefix, settings.MAX_DEPTH)
        existing = set(link["existing"])
        waiting = [(item, folders) for item, folders in files if item["id"] not in existing]
        waiting.sort(key=lambda pair: (pair[0]["createdTime"], pair[0]["name"]))
        print(f"\n{link['connection']}: {'/'.join(prefix)}  ({len(waiting)} new of {len(files)} files)")
        seen: dict[str, str] = {}
        for item, folders in waiting:
            print_file(item, folders, classify(folders, len(prefix) - 1, lists, settings.MAX_DEPTH), seen)
        for note in notes:
            print(f"  {note}")


def resolve(drive: Drive, ref: str) -> dict:
    """A folder by id, or on Google by a path that starts at a shared folder's name."""
    if isinstance(drive, LocalDrive) or "/" not in ref:
        return drive.get(ref)
    first, *rest = ref.split("/")
    matches = [root for root in drive.shared_roots() if root["name"] == first]
    for name in rest:
        if len(matches) != 1:
            break
        matches = [child for child in drive.children(matches[0]["id"])
                   if child["name"] == name and child["mimeType"] == FOLDER]
    if len(matches) != 1:
        raise SystemExit(f"{ref}: {len(matches)} folders match that path; use the folder id")
    return drive.get(matches[0]["id"])


def walk(children: Children, root_id: str, prefix: list[str], max_depth: int | None) -> tuple[list, list[str]]:
    """Files under root with their folder names, plus notes on folders that were not walked."""
    files, notes, queue = [], [], [(root_id, prefix)]
    while queue:
        folder_id, folders = queue.pop()
        try:
            items = children(folder_id)
        except DriveError as exc:
            notes.append(f"not readable: {'/'.join(folders)} ({exc})")
            continue
        for item in items:
            path = folders + [item["name"]]
            if item["mimeType"] != FOLDER:
                files.append((item, folders))
            elif max_depth is not None and len(path) - len(prefix) > max_depth:
                notes.append(f"too deep, not walked: {'/'.join(path)}")
            else:
                queue.append((item["id"], path))
    return files, notes


def ancestry(drive: Drive, item: dict) -> list[str]:
    """Folder names from the highest folder the address can read down to item."""
    names = [item["name"]]
    while item.get("parents"):
        parent_id = item["parents"][0]
        if parent_id == item.get("driveId"):
            names.append(drive.drive_name(parent_id))
            break
        try:
            item = drive.get(parent_id)
        except DriveError as exc:
            if exc.status not in (403, 404):
                raise
            break
        names.append(item["name"])
    return names[::-1]


def children_for(drive: Drive, use_index: bool) -> Children:
    """Per-folder calls, or (--all) one listing of everything indexed by parent."""
    if not use_index:
        return drive.children
    start, index = time.perf_counter(), defaultdict(list)
    items = drive.everything()
    for item in items:
        for parent in item.get("parents", []):
            index[parent].append(item)
    print(f"one listing: {len(items)} items, {drive.calls} API calls, {time.perf_counter() - start:.2f} s")
    return lambda folder_id: index.get(folder_id, [])


def without(children: Children, skip: set[str]) -> Children:
    """Leave out folders linked to another connection; their files belong there (GD-12)."""
    return lambda folder_id: [child for child in children(folder_id) if child["id"] not in skip]


def print_file(item: dict, folders: list[str], result: str, seen: dict[str, str]) -> None:
    """One waiting file with its entry type, its checks and Google's details (GD-68)."""
    path = "/".join(folders + [item["name"]])
    reasons, digest = blockers(item), item.get("sha256Checksum")
    if result in NOT_OFFERED:
        reasons.insert(0, NOT_OFFERED[result])
    elif digest in seen:
        reasons.append(f"duplicate of {seen[digest]}")
    elif digest:
        seen[digest] = path
    print(f"  {result:<17} {path}")
    print(f"  {'':<17} {'; '.join(reasons) or 'importable'}")
    print(f"  {'':<17} created {item.get('createdTime')}  modified {item['modifiedTime']}  "
          f"owner {_owner(item)}  last change {_person(item.get('lastModifyingUser'))}  "
          f"sha256 {(digest or 'none')[:12]}")


def blockers(item: dict) -> list[str]:
    """Why the upload window could not import the file yet (GD-45, GD-54, C-19)."""
    mime, reasons = item["mimeType"], []
    if mime == SHORTCUT:
        reasons.append("shortcut, not followed")
    elif mime.startswith(GOOGLE_APPS):
        reasons.append("Google Docs file")
    elif not type_allowed(mime, item["name"]):
        reasons.append(f"type {mime} not allowed")
    elif "size" not in item:
        reasons.append("size not reported")
    elif int(item["size"]) > settings.MAX_FILE_MB * 1024 * 1024:
        reasons.append(f"{int(item['size']) / 1048576:.1f} MB is over {settings.MAX_FILE_MB} MB")
    can_download = item.get("capabilities", {}).get("canDownload")
    if can_download is not True:
        reasons.append("download switched off" if can_download is False else "download not reported")
    age = (datetime.now(timezone.utc) - _parse(item["modifiedTime"])).total_seconds()
    if age < settings.SETTLE_SECONDS:
        reasons.append(f"not ready, changed {age:.0f} s ago")
    return reasons


def type_allowed(mime: str, name: str) -> bool:
    """eScanX's rule (src/api/utils.py:144-173): the MIME type decides unless it is octet-stream."""
    if mime and mime != "application/octet-stream":
        return mime in settings.SUPPORTED_MIME_TYPES
    return PurePath(name).suffix.lower() in settings.SUPPORTED_EXTENSIONS


def load_links(source: str) -> dict[str, dict]:
    """Linked folders saved for this source, by folder id; none before the first link."""
    if not settings.STATE_FILE.exists():
        return {}
    return json.loads(settings.STATE_FILE.read_text(encoding="utf-8")).get(source, {})


def save_links(source: str, links: dict[str, dict]) -> None:
    state = {}
    if settings.STATE_FILE.exists():
        state = json.loads(settings.STATE_FILE.read_text(encoding="utf-8"))
    state[source] = links
    settings.STATE_FILE.parent.mkdir(exist_ok=True)
    settings.STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _owner(item: dict) -> str:
    owners = item.get("owners")
    return _person(owners[0]) if owners else "none (shared drive)"


def _person(user: dict | None) -> str:
    if not user:
        return "not reported"
    return user.get("emailAddress") or user.get("displayName") or "not reported"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _action(event: dict) -> str:
    detail = event.get("primaryActionDetail", {})
    kind = next(iter(detail), "unknown")
    if kind == "move":
        added = [p.get("driveItem", {}).get("title", "?") for p in detail["move"].get("addedParents", [])]
        return f"move into {', '.join(added) or '?'}"
    if kind == "create":
        return f"create ({next(iter(detail['create']), '?')})"
    return kind


def _actor(event: dict) -> str:
    actor = (event.get("actors") or [{}])[0]
    known = actor.get("user", {}).get("knownUser")
    if known:
        return known.get("personName", "?") + (" (this address)" if known.get("isCurrentUser") else "")
    return next(iter(actor.get("user") or actor), "unknown")


def _targets(event: dict) -> str:
    return ", ".join(t.get("driveItem", {}).get("title", "?") for t in event.get("targets", []))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("google", "local"), default="google")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("access", help="shared folders and drives the address can read")
    link = sub.add_parser("link", help="link a business folder to a connection")
    link.add_argument("folder", help="folder id, or a path that starts at a shared folder's name")
    link.add_argument("connection")
    link.add_argument("--all-new", action="store_true", help="record no existing files")
    new = sub.add_parser("new", help="waiting files per linked folder")
    new.add_argument("--all", action="store_true", help="one listing of everything, then walk it")
    sub.add_parser("hash", help="download a file and compare SHA-256").add_argument("file_id")
    sub.add_parser("activity", help="who added or moved files, and when").add_argument("folder_id")
    return parser


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args()
    probe = Probe(args.source)
    commands = {
        "access": probe.access,
        "link": lambda: probe.link(args.folder, args.connection, args.all_new),
        "new": lambda: probe.new(args.all),
        "hash": lambda: probe.hash(args.file_id),
        "activity": lambda: probe.activity(args.folder_id),
    }
    try:
        commands[args.command]()
    except DriveError as exc:
        print(f"Drive call failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
