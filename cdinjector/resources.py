"""Locating bundled resources (emulator cores, makerom, bannertool) and running tools."""

import os
import subprocess
import sys
from pathlib import Path


def resource_dir() -> Path:
    # PyInstaller unpacks bundled data under sys._MEIPASS.
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def core_dir(core: str) -> Path:
    return resource_dir() / "cores" / core


def tool(name: str) -> str:
    folder = "windows" if os.name == "nt" else "linux"
    exe = resource_dir() / "tools" / folder / (name + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        raise FileNotFoundError(f"bundled tool missing: {exe}")
    return str(exe)


def run_tool(cmd, timeout=900, cwd=None):
    """Run a bundled tool (never through a shell) without flashing a console window on Windows. A tool that
    hangs is stopped after `timeout` seconds instead of leaving the app waiting for ever.

    makerom and bannertool only understand file names in the Windows code page, so a path with, say, Japanese
    letters in it reaches them as "???". Callers therefore run them inside the work folder (`cwd`) and pass
    plain-ASCII names relative to it."""
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags, timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=cwd, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{Path(cmd[0]).name} took too long and was stopped.")
    if r.returncode != 0:
        name = Path(cmd[0]).name
        raise RuntimeError(f"{name} failed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}".strip())
    return r


def font_path(bold=True):
    names = (["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"])
    folders = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
               Path("/usr/share/fonts/truetype/dejavu"),
               Path("/System/Library/Fonts/Supplemental")]
    for folder in folders:
        for n in names:
            if (folder / n).is_file():
                return str(folder / n)
    return None


def font_path_rounded():
    """A heavy, rounded font for the "Virtual Console" wordmark (the caller slants it), or None."""
    names = ["ARLRDBD.TTF", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"]
    folders = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
               Path("/usr/share/fonts/truetype/dejavu"),
               Path("/System/Library/Fonts/Supplemental")]
    for n in names:
        for folder in folders:
            if (folder / n).is_file():
                return str(folder / n)
    return None
