"""POC settings; each value can be overridden by the DRIVE_POC_* variable beside it."""

import os
from pathlib import Path

POC_DIR = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    """The environment variable's value, or the POC default."""
    return os.environ.get(name, default)


KEY_FILE = Path(_env("DRIVE_POC_KEY_FILE", str(Path.home() / ".escanx-drive-poc" / "sa-key.json")))
DRIVE_URL = _env("DRIVE_POC_DRIVE_URL", "https://www.googleapis.com/drive/v3")
ACTIVITY_URL = _env("DRIVE_POC_ACTIVITY_URL", "https://driveactivity.googleapis.com/v2")
TOKEN_URL = _env("DRIVE_POC_TOKEN_URL", "https://oauth2.googleapis.com/token")
SCOPES = " ".join((
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
))
TIMEOUT_SECONDS = float(_env("DRIVE_POC_TIMEOUT_SECONDS", "15"))
SETTLE_SECONDS = int(_env("DRIVE_POC_SETTLE_SECONDS", "120"))
MAX_DEPTH = int(_env("DRIVE_POC_MAX_DEPTH", "5"))
MAX_FILE_MB = int(_env("DRIVE_POC_MAX_FILE_MB", "10"))

LISTS_FILE = POC_DIR / "lists.txt"
CASES_FILE = POC_DIR / "cases.txt"
MOCK_DIR = POC_DIR / "mock-drive"
MOCK_SHARED_FOLDER = "Clients"
STATE_FILE = POC_DIR / "state" / "links.json"

# Copied from eScanX src/shared/constants.py:23-30 (SUPPORTED_FORMATS); keep the two in step.
SUPPORTED_FORMATS: dict[str, str] = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".heic": "image/heic",
    ".webp": "image/webp",
}
SUPPORTED_MIME_TYPES = frozenset(SUPPORTED_FORMATS.values())
SUPPORTED_EXTENSIONS = frozenset(SUPPORTED_FORMATS)
