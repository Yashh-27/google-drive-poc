"""Read-only Drive access as the service account, and a local stand-in over mock-drive/."""

import hashlib
import json
import mimetypes
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

import settings

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
GOOGLE_APPS = "application/vnd.google-apps."
FILE_FIELDS = (
    "id,name,mimeType,size,createdTime,modifiedTime,parents,driveId,"
    "owners(displayName,emailAddress),lastModifyingUser(displayName,emailAddress),"
    "sha256Checksum,capabilities(canDownload),shortcutDetails"
)
ALL_DRIVES = {"corpora": "allDrives", "includeItemsFromAllDrives": "true", "supportsAllDrives": "true"}
JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class DriveError(RuntimeError):
    """A Drive call failed; status is the HTTP status Google (or the mock) gave."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(f"{status} {reason}")
        self.status = status


class GoogleDrive:
    """Drive and Drive Activity calls as the service account in settings.KEY_FILE."""

    def __init__(self) -> None:
        if not settings.KEY_FILE.is_file():
            raise SystemExit(f"No key file at {settings.KEY_FILE}; set DRIVE_POC_KEY_FILE.")
        self._key = json.loads(settings.KEY_FILE.read_text(encoding="utf-8"))
        self._http = httpx.Client(timeout=settings.TIMEOUT_SECONDS, follow_redirects=True)
        self._token, self._expires = "", 0.0
        self.calls = self.incomplete = 0

    def children(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and trashed = false"
        return list(self._pages("/files", {"q": query, **ALL_DRIVES}, "files"))

    def everything(self) -> list[dict]:
        return list(self._pages("/files", {"q": "trashed = false", **ALL_DRIVES}, "files"))

    def get(self, file_id: str) -> dict:
        params = {"fields": FILE_FIELDS, "supportsAllDrives": "true"}
        return self._json("GET", f"{settings.DRIVE_URL}/files/{file_id}", params=params)

    def drive_name(self, drive_id: str) -> str:
        url = f"{settings.DRIVE_URL}/drives/{drive_id}"
        return self._json("GET", url, params={"fields": "name"})["name"]

    def shared_roots(self) -> list[dict]:
        query = f"sharedWithMe = true and mimeType = '{FOLDER}' and trashed = false"
        folders = [f | {"kind": "shared folder"} for f in self._pages("/files", {"q": query, **ALL_DRIVES}, "files")]
        return folders + [d | {"kind": "shared drive"} for d in self._pages("/drives", {}, "drives")]

    def download(self, file_id: str) -> bytes:
        """The file's bytes, stopping as soon as it passes the size limit."""
        cap, data = settings.MAX_FILE_MB * 1024 * 1024, bytearray()
        params = {"alt": "media", "supportsAllDrives": "true"}
        with self._stream(f"{settings.DRIVE_URL}/files/{file_id}", params) as reply:
            if not reply.is_success:
                reply.read()
                raise DriveError(reply.status_code, _reason(reply))
            for chunk in reply.iter_bytes():
                data += chunk
                if len(data) > cap:
                    raise DriveError(413, f"over the {settings.MAX_FILE_MB} MB limit")
        return bytes(data)

    def activity(self, folder_id: str) -> list[dict]:
        """Create, move, rename, delete and restore events for items under the folder."""
        body: dict[str, Any] = {
            "ancestorName": f"items/{folder_id}", "pageSize": 100,
            "filter": "detail.action_detail_case:(CREATE MOVE RENAME DELETE RESTORE)"}
        events: list[dict] = []
        while True:
            page = self._json("POST", f"{settings.ACTIVITY_URL}/activity:query", json=body)
            events += page.get("activities", [])
            if "nextPageToken" not in page:
                return events
            body = {**body, "pageToken": page["nextPageToken"]}

    def _pages(self, path: str, params: dict[str, str], key: str) -> Iterator[dict]:
        """Every item of a paged list call."""
        wanted = f"incompleteSearch,files({FILE_FIELDS})" if key == "files" else "drives(id,name)"
        params = {**params, "fields": f"nextPageToken,{wanted}",
                  "pageSize": "1000" if key == "files" else "100"}
        while True:
            body = self._json("GET", f"{settings.DRIVE_URL}{path}", params=params)
            self.incomplete += bool(body.get("incompleteSearch"))
            yield from body.get(key, [])
            if "nextPageToken" not in body:
                return
            params = {**params, "pageToken": body["nextPageToken"]}

    def _json(self, method: str, url: str, **kwargs: Any) -> dict:
        self.calls += 1
        reply = self._http.request(method, url, headers=self._auth(), **kwargs)
        if not reply.is_success:
            raise DriveError(reply.status_code, _reason(reply))
        return reply.json()

    def _stream(self, url: str, params: dict[str, str]) -> Any:
        self.calls += 1
        return self._http.stream("GET", url, params=params, headers=self._auth())

    def _auth(self) -> dict[str, str]:
        """Bearer header; a new token is signed a minute before the old one expires."""
        if time.time() > self._expires - 60:
            now = int(time.time())
            claims = {"iss": self._key["client_email"], "scope": settings.SCOPES,
                      "aud": settings.TOKEN_URL, "iat": now, "exp": now + 3600}
            assertion = jwt.encode(claims, self._key["private_key"], algorithm="RS256")
            reply = self._http.post(settings.TOKEN_URL, data={"grant_type": JWT_GRANT, "assertion": assertion})
            if not reply.is_success:
                raise DriveError(reply.status_code, _reason(reply))
            body = reply.json()
            self._token, self._expires = body["access_token"], now + int(body["expires_in"])
        return {"Authorization": f"Bearer {self._token}"}


class LocalDrive:
    """The same calls over mock-drive/, using paths relative to it as file ids."""

    def __init__(self) -> None:
        self._root = settings.MOCK_DIR
        self.calls = self.incomplete = 0

    def children(self, folder_id: str) -> list[dict]:
        self.calls += 1
        return [self._item(path) for path in sorted(self._path(folder_id).iterdir())]

    def everything(self) -> list[dict]:
        self.calls += 1
        return [self._item(path) for path in sorted(self._root.rglob("*"))]

    def get(self, file_id: str) -> dict:
        self.calls += 1
        return self._item(self._path(file_id))

    def drive_name(self, drive_id: str) -> str:
        raise DriveError(501, "the local mock has no shared drives")

    def shared_roots(self) -> list[dict]:
        return [self._item(path) | {"kind": "shared folder"} for path in sorted(self._root.iterdir()) if path.is_dir()]

    def download(self, file_id: str) -> bytes:
        self.calls += 1
        return self._path(file_id).read_bytes()

    def activity(self, folder_id: str) -> list[dict]:
        raise DriveError(501, "only Google records activity")

    def _path(self, file_id: str) -> Path:
        path = self._root / file_id
        if not path.exists():
            raise DriveError(404, f"{file_id} not found in {self._root.name}")
        return path

    def _item(self, path: Path) -> dict:
        parent, stat = path.parent.relative_to(self._root), path.stat()
        item = {"id": path.relative_to(self._root).as_posix(), "name": path.name,
                "parents": [] if parent == Path(".") else [parent.as_posix()],
                "createdTime": _iso(stat.st_ctime), "modifiedTime": _iso(stat.st_mtime),
                "owners": [{"displayName": "local mock"}], "capabilities": {"canDownload": True}}
        if path.is_dir():
            return item | {"mimeType": FOLDER}
        data = path.read_bytes()
        return item | {"mimeType": _mime(path), "size": str(len(data)),
                       "sha256Checksum": hashlib.sha256(data).hexdigest()}


def open_source(name: str) -> GoogleDrive | LocalDrive:
    """The Drive to probe: 'google' for the live test, 'local' for mock-drive/."""
    return GoogleDrive() if name == "google" else LocalDrive()


def _reason(reply: httpx.Response) -> str:
    """Google's error text; request headers and tokens are never included."""
    try:
        error = reply.json().get("error")
    except ValueError:
        return reply.text[:200] or reply.reason_phrase
    if isinstance(error, dict):
        reasons = ",".join(e.get("reason", "") for e in error.get("errors", []))
        return f"{error.get('message', '')} [{reasons}]"
    return f"{error}: {reply.json().get('error_description', '')}"


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _mime(path: Path) -> str:
    known = settings.SUPPORTED_FORMATS.get(path.suffix.lower())
    return known or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
