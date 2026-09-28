# Changelog

## 1.0.3 (2026-09-28)

- The program is now `CD-Injector-3DS.exe` in a `CD-Injector-3DS` folder (it was `CD Injector 3DS.exe`), so the
  command line no longer needs quotes around it. The app's name, your settings and the CIAs it makes are unchanged.
  If you pinned the old .exe to the taskbar or Start menu, pin the new one instead.

## 1.0.2 (2026-09-28)

- Fixed: with no picture chosen, the banner's "PC ENGINE CD" label was wider than the screen it sits on and got
  cut off at both edges. It now shrinks to fit. Only CIAs made without a picture are affected; remake one to get
  the fixed banner (the title ID stays the same, so it installs over the old one and keeps its saves).
- The README has a screenshot, a quick start and an FAQ.

## 1.0.1 (2026-09-27)

Maintenance release. CIAs are the same as with 1.0.0.

- Built with Python 3.14.7 (was 3.14.3) and PyInstaller 6.22.3 (was 6.19.0), which bring the latest security fixes
  for the runtime inside the app.
- The app no longer contains Python's networking modules (sockets and SSL). It never used them; now they aren't
  there at all, and the download is a little smaller.
- The command line shows "..." instead of a character some consoles can't display.
- Unused code removed.

## 1.0.0 (2026-09-27)

First public release.

### Fixed
- Games, titles and folders with non-English names now work. Before, a Japanese title, a Japanese Windows user
  name or an output folder with letters outside the Windows code page made makerom fail, and an accented or
  Japanese title turned into "???" under the Home Menu icon. makerom and bannertool now run inside the work folder
  with plain names, the icon file is written by the app itself (titles in any language), and names inside the CIA
  are plain ASCII.
- A CIA is saved under its real name only once it is complete, so a failed build never leaves a half-written CIA.
- The command line no longer stops with an error when it prints a title or path its console can't show.
- A damaged picture that Pillow reports with an unusual error is now a normal error message.

### Changed
- makerom is now the official v0.18.4 release (MIT) instead of an older v0.15 copy from the emus3ds repository.
  v0.15 counted the emulator's uninitialised memory twice, which reserved an extra 4 MB (PicoDrive) or 6.5 MB (TemperPCE)
  of the 3DS's memory for nothing. Everything else in the CIA (RomFS, icon, banner, program code) is byte-identical.
- The picture, banner sound and plate font are checked before the game is copied, so a bad file is reported at
  once. A banner sound must be a PCM `.wav` of at most 3 seconds, or a `.bcwav`.
- The Windows release includes the Python, Tcl/Tk and Pillow licence texts (`licenses\`), carries version details
  on the .exe, and ships the emulator source archive next to the zip with both in `SHA256SUMS.txt`.
- `--version` on the command line.

## 0.5.0

- The banner is the title screen in a frame of any color, with the Virtual Console plate below. The earlier 3D
  console banners were removed.
- Banners and icons exported from NSUI can be used on a CD game's CIA, with the blank title plate drawn in.
- New five-step window with a help page, and a "More options" dialog (icon fit, banner sound, plate font).
- Security hardening: size and structure checks on every file the user picks, fuzz tests, hidden-character scan.

## 0.2.0

- Castlevania: Rondo of Blood froze after its opening cutscene with TemperPCE's fast CPU core; CIAs now default to
  the compatible core.
- Simpler window: game, BIOS, details, create.

## 0.1.0

- First working build: per-game CIAs for PC Engine CD and Sega CD with the game and BIOS inside.
