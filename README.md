# Google Drive import POC

Stand-alone proof of concept for the Google Drive import requirements agreed on 20 Nov 2026. It answers the Google questions in their section 10 and tests the folder-name rules on mock folder trees; nothing here touches eScanX.

## Run with

- eScanX's Python, from this folder: `$py = "C:\Users\hp\Desktop\Erichsol_Dir\eScanX-API\.venv\Scripts\python.exe"`, then `& $py <script> ...`.
- Settings live in `settings.py`; each one can be overridden by its `DRIVE_POC_*` environment variable.
- The service-account key goes in `C:\Users\hp\.escanx-drive-poc\sa-key.json` (or set `DRIVE_POC_KEY_FILE`). Never put it in this folder.

## Files

- `lists.txt`: the mock organisation's folder names per entry type, and the ignored names.
- `cases.txt`: mock folder trees, which folders are linked, and the result each file must get.
- `rules.py`: the folder-name rules (GD-12, GD-20 to GD-26), with no Google calls.
- `check_rules.py`: runs every case through the rules; exit code 1 on any failure.
- `make_mock_drive.py`: builds `mock-drive/` from the cases, plus size and type test files; `--bulk N` adds N PDFs for timing.
- `drive.py`: read-only Google Drive and Drive Activity calls, and `LocalDrive`, the same calls over `mock-drive/`.
- `probe.py`: the commands `access`, `link`, `new`, `hash` and `activity`; `--source local` runs them on `mock-drive/`.
- Made at run time: `mock-drive/` and `state/links.json`, the linked folders and the files they held when linked.

## Offline, no Google needed

1. `& $py check_rules.py` prints PASS or FAIL for every case.
2. `& $py make_mock_drive.py --bulk 500` rebuilds `mock-drive/` and prints the two folders Windows can't hold, to make by hand in Drive.
3. `& $py probe.py --source local link "Clients/Acme Ltd" Acme`, then add a file under `mock-drive\Clients\Acme Ltd\Expenses` and run `& $py probe.py --source local new`.

## For Sir

1. Create a new Google Cloud project for testing only, not the one behind eScanX's Google sign-in.
2. Enable the Google Drive API and the Drive Activity API.
3. Create one service account with no project roles; optionally a second one for GD-06.
4. Hand over its JSON key privately, not by email or chat. If a policy blocks keys, say so: the POC then signs in by impersonation.
5. Send the service account's email address.

## Live run

1. `& $py make_mock_drive.py --bulk 500` for a fresh copy.
2. In a test Google account, drag `mock-drive\Clients` into drive.google.com. Inside `Clients/Acme Ltd`, make the two folders the script printed (`EXPENSES` with `p.pdf`, ` Expenses ` with `q.pdf`).
3. Share `Clients` with the service account's email as Viewer.
4. `& $py probe.py access` must list `Clients`.
5. Link every `link:` folder in `cases.txt`, plus `Clients/Bulk Ltd`, with `--all-new`: for example `& $py probe.py link "Clients/Acme Ltd" Acme --all-new`. Then run `new` and `new --all`, so every mock file is classified on real Drive names and both listings are timed.
6. Link the same folders again without `--all-new`; `new` must now list nothing. Then work through the scenarios below, running `new` after each.
7. `& $py probe.py hash <file id>` on a PDF, the HEIC photo and the download-off file; `& $py probe.py activity <Clients folder id>`.
8. In a Google Workspace account, make a shared drive, add the service account as a Viewer member, upload `Clients/Acme Ltd` into it, link it and repeat steps 4 to 7 in short.

Folder and file ids are in the Drive address: `.../folders/<id>` and `.../file/d/<id>/`. `link` also takes a path that starts at a shared folder's name.

## Scenarios (requirement it tests)

- Another person adds files to a linked folder (GD-41).
- Move a file from Payroll into Expenses (C-01).
- Move or rename a file that was there at linking (GD-44).
- Rename the business folder, then move it inside `Clients` (C-14).
- Upload a new version of a file (C-03).
- Bin a new file, run `new`, restore it, run `new` again (C-06).
- Copy a file (C-04).
- Add a Google Doc and a shortcut (C-11, C-12).
- Add a HEIC photo and a WEBP image from a phone (eScanX allows `image/heic` and `image/webp`).
- Switch off downloading on one file; restrict a subfolder in the shared drive (C-19).
- Make two same-named folders side by side, and a folder whose name holds `/` (C-18).
- Rename an entry-type folder to a name on no list (C-13).
- Unshare the business folder (C-15).
- Change a file just before running `new` (C-09).
- Optional: show that a second service account cannot see these folders (GD-06).

## Record in the findings

Write the answers to `C:\Users\hp\Desktop\Erichsol_Dir\google-drive-poc-findings.md`, with the command output as evidence:

- whether `access` lists the shared folder and the shared drive;
- whether files added by another person are visible;
- who added a file, as file details and Drive Activity report it, in My Drive and in a shared drive;
- the date a moved-in file shows, from file details and from Drive Activity;
- listing time for `new` and `new --all` on Bulk Ltd and Acme;
- what a restricted subfolder and a download-off file look like;
- whether Google's SHA-256 is present and matches the downloaded file;
- the MIME types Google reports for HEIC, WEBP, a Google Doc and a shortcut;
- each scenario's result against the requirement it tests;
- whether Google marked any listing incomplete.
