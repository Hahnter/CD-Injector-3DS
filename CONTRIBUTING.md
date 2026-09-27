# Contributing

Bug reports, compatibility reports and pull requests are welcome.

## Reports

- **A game works or doesn't:** open a compatibility report (Issues, New issue). Say which 3DS model you used,
  the game's region, which CPU core you tried (PC Engine CD) and what happened. Failures are as useful as
  successes.
- **The app did something wrong:** open a bug report with the steps, the version (in the window title) and the
  full error message.
- **A security problem:** don't open a public issue. See [SECURITY.md](SECURITY.md).

Never attach or link games, BIOS files or CIAs, including ones you made yourself. Issues that do will be deleted.

## Code

1. Make a virtual environment: `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`
   (add `requirements-build.txt` to package the app).
2. Run the checks before sending a change:
   - `python scripts/hygiene.py` (hidden characters and file metadata; `--fix` cleans them)
   - `python -m unittest discover -s tests -t .`
3. Keep changes focused, and add a test for any bug you fix. The CI runs the same checks on every pull request.

Files the user chooses are the app's only untrusted input, so anything that reads them needs size limits and
must fail with an ordinary error message. `tests/test_security.py` shows the pattern.

By contributing you agree that your code is released under the project's MIT License.
