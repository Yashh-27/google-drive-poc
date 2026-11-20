"""Build mock-drive/: the mock folder trees as local files, to drag into a test Drive."""

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

import settings
from check_rules import load_cases

EXTRAS_DIR = f"{settings.MOCK_SHARED_FOLDER}/Acme Ltd/Expenses/2025/Mar"
BULK_DIR = f"{settings.MOCK_SHARED_FOLDER}/Bulk Ltd/Expenses/2025"
MONTHS = ("01 Jan", "02 Feb", "03 Mar", "04 Apr", "05 May", "06 Jun",
          "07 Jul", "08 Aug", "09 Sep", "10 Oct", "11 Nov", "12 Dec")
WINDOWS_BAD = set('<>:"\\|?*')


def pdf_bytes(label: str) -> bytes:
    """A valid one-page PDF printing label, so every mock file has its own SHA-256."""
    text = label.encode("latin-1", "replace")
    text = text.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    stream = b"BT /F1 10 Tf 40 760 Td (" + text + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def unsafe_on_windows(parts: list[str]) -> bool:
    """Windows drops trailing spaces and dots from names and refuses some characters."""
    return any(part != part.rstrip(" .") or WINDOWS_BAD & set(part) for part in parts)


def clashes(path: str, seen: dict[str, str]) -> bool:
    """A folder differing from an existing one only by case; Windows would merge the two."""
    parts = path.split("/")
    for end in range(1, len(parts)):
        prefix = "/".join(parts[:end])
        if seen.setdefault(prefix.casefold(), prefix) != prefix:
            return True
    return False


def write_cases(root: Path) -> list[str]:
    """One PDF per case path; returns the paths to make by hand in Drive."""
    _, cases = load_cases()
    seen: dict[str, str] = {}
    by_hand = []
    for case in cases:
        parts = case.path.split("/")
        if unsafe_on_windows(parts) or clashes(case.path, seen):
            by_hand.append(f"{case.case_id}: {case.path}")
            continue
        target = root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf_bytes(f"{case.case_id} {case.path}"))
    return by_hand


def write_extras(root: Path) -> None:
    """Files for the size, type and duplicate checks (C-04, C-10, C-11)."""
    folder = root / EXTRAS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    oversize = (settings.MAX_FILE_MB + 1) * 1024 * 1024
    (folder / "big-photo.jpg").write_bytes(b"\xff\xd8\xff\xe0" + bytes(oversize))
    with zipfile.ZipFile(folder / "bundle.zip", "w") as archive:
        archive.writestr("inside.pdf", pdf_bytes("inside the zip"))
    (folder / "costs.xlsx").write_bytes(b"placeholder: not a real spreadsheet")
    (folder / "invoice.eml").write_text(
        "From: supplier@example.com\nSubject: Invoice\n\nSee the attached invoice.\n", encoding="utf-8")
    receipt = pdf_bytes("March receipt")
    (folder / "march-receipt.pdf").write_bytes(receipt)
    (folder / "march-receipt-copy.pdf").write_bytes(receipt)


def write_bulk(root: Path, count: int) -> None:
    """count small PDFs spread over month folders, for timing the listing."""
    for number in range(count):
        folder = root / BULK_DIR / MONTHS[number % len(MONTHS)]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"bulk-{number:04d}.pdf").write_bytes(pdf_bytes(f"bulk {number}"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk", type=int, default=0, help="extra PDFs under Bulk Ltd, for timing")
    args = parser.parse_args()
    if settings.MOCK_DIR.exists():
        shutil.rmtree(settings.MOCK_DIR)
    by_hand = write_cases(settings.MOCK_DIR)
    write_extras(settings.MOCK_DIR)
    write_bulk(settings.MOCK_DIR, args.bulk)
    count = sum(1 for path in settings.MOCK_DIR.rglob("*") if path.is_file())
    print(f"{count} files written under {settings.MOCK_DIR}")
    for line in by_hand:
        print(f"make by hand in Drive (Windows can't hold it): {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
