# Security

## What this app does and doesn't do

- It **never connects to the internet**. It has no update check, no telemetry and no analytics. (The tests fail
  if networking code is added.)
- It reads only the files you choose: the game's `.cue` and `.bin` files, the BIOS, a picture, and an optional NSUI
  banner, icon, sound or font.
- It writes only the CIA, temporary files (deleted when it finishes) and one small settings file,
  `%APPDATA%\CD Injector 3DS\settings.json`, holding the paths and colors you chose.
- It runs its two helper programs (`makerom` and `bannertool`) directly with a list of arguments, never through a
  shell, and stops them if they hang. They run inside a private work folder and only ever get plain relative file
  names made by the app, never a name taken from your files.

## Supported versions

Only the latest release gets fixes. Please check you're on it before reporting.

## Files from outside are treated as untrusted

Every file you choose is checked before it is used, and a bad one gives an error message, not a crash:

- `.cue` sheets: size and track-count limits; only files that sit in the `.cue`'s own folder are packed, so a
  crafted sheet can't pull another file on your PC into a CIA (shortcuts to files elsewhere are refused too).
- NSUI banners and icons: size limits, structure checks, and a cap on how far a compressed model may expand (a
  "decompression bomb" is refused). A damaged banner is refused rather than put in a CIA, because a broken banner
  can stop the Home Menu showing the game.
- Pictures: a pixel limit against decompression bombs, and each picture is fully decoded before the game is
  copied.
- Banner sounds: format, length and size checks.
- Titles: control and invisible characters are removed, and Windows reserved names (CON, NUL, ...) can't be used
  as file names.
- The settings file: only plain text values are accepted.

`tests/test_security.py` tries all of this with hostile and randomly damaged files.

## Checking a download

Each release comes with `SHA256SUMS.txt`. In PowerShell:

    Get-FileHash .\CD-Injector-3DS-vX.Y.Z-windows.zip -Algorithm SHA256

The result must match the line in `SHA256SUMS.txt`. The program itself is **not code-signed**, so Windows
SmartScreen may warn about it the first time; that is expected for an unsigned program.

## Reporting a problem

Please report security problems privately, not in a public issue: use GitHub's "Report a vulnerability" button
(the repository's Security tab). Include the steps and, if you can, a sample file that triggers it. Ordinary bugs
can go in normal issues.

## For contributors

- `python scripts/hygiene.py` checks for invisible characters, look-alike letters and hidden file metadata. Run it
  before committing; `--fix` cleans what it finds.
- `python -m unittest discover -s tests -t .` runs every test. `FUZZ_ITERATIONS=2000` makes the damaged-file test
  much longer. The banner fuzz tests need real NSUI banners, which can't be shipped: list yours in
  `CDI_TEST_BANNERS` (separated by `;` on Windows).
- Never commit games, BIOS files, CIAs, or Nintendo-derived files (see `.gitignore`).
- Build in a virtual environment: `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements-build.txt`
  and `scripts\build_windows.ps1 -Python .venv\Scripts\python.exe`. The versions in `requirements*.txt` are exact.
- Before every release, check that no pinned library has a published security advisory, for example:
  `gh api "advisories?ecosystem=pip&affects=pillow@12.3.0" --jq length` (0 means none). Do this for each pinned
  package. Pillow matters most: it opens the pictures and fonts users choose. Dependabot does the same once the
  repository is on GitHub.
