"""Downloading a game's picture from libretro's thumbnail collection, only when the user asks for it.

This is the only part of the app that goes online, and it does one thing: fetch a single picture over HTTPS from
libretro's thumbnails on GitHub (the collection RetroArch and NSUI use) for a game the app recognised. The picture
must be a real PNG of a sensible size. It is kept in the app's settings folder, laid out like RetroArch's
thumbnails, so it is downloaded only once and found offline from then on. Nothing about the user or the PC is sent.
"""

import io
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from . import APP_NAME, VERSION
from .gameinfo import THUMBNAIL_KINDS, THUMBNAIL_SYSTEMS, downloaded_pictures, picture_names, thumbnail_file_name

HOST = "https://raw.githubusercontent.com/libretro-thumbnails"
REPOS = {"pce": "NEC_-_PC_Engine_CD_-_TurboGrafx-CD", "segacd": "Sega_-_Mega-CD_-_Sega_CD"}
MAX_BYTES = 8 * 1024 * 1024                  # a title screen or box art is far smaller
TIMEOUT = 20                                 # seconds per request
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class DownloadError(Exception):
    """The picture couldn't be downloaded."""


def picture_url(system, kind, name):
    return f"{HOST}/{REPOS[system]}/master/{kind}/{urllib.parse.quote(thumbnail_file_name(name) + '.png')}"


def _fetch(url, opener):
    """The body of a picture at `url`, or None when there is no such picture (HTTP 404)."""
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME.replace(' ', '-')}/{VERSION}"})
    try:
        with opener(request, timeout=TIMEOUT) as r:
            if not r.geturl().startswith(HOST + "/"):            # a redirect somewhere else is not followed up
                raise DownloadError("libretro's thumbnails sent the download somewhere else, so it was stopped.")
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise DownloadError(f"libretro's thumbnails answered with an error ({e.code}).")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise DownloadError(f"Couldn't reach libretro's thumbnails ({getattr(e, 'reason', e)}). "
                            "Is this PC online?")
    if len(data) > MAX_BYTES:
        raise DownloadError("The picture is far too big, so it wasn't used.")
    return data


def download_picture(system, name, folder=None, opener=urllib.request.urlopen):
    """A picture for the game called `name` (its Redump name, as gameinfo finds it): the title screen if libretro has
    one, else a screenshot, else box art, each looked for under the names gameinfo.picture_names gives. Returns the
    saved file, or None when libretro has no picture of the game. Raises DownloadError when it can't be downloaded."""
    if system not in REPOS or not name:
        return None
    names = [n for n in picture_names(system, [name]) if not n.startswith(".")]
    folder = Path(folder) if folder else downloaded_pictures()
    for kind in THUMBNAIL_KINDS:
        kept = [folder / THUMBNAIL_SYSTEMS[system] / kind / (thumbnail_file_name(n) + ".png") for n in names]
        for dest in kept:
            if dest.is_file():
                return dest
        for n, dest in zip(names, kept):
            data = _fetch(picture_url(system, kind, n), opener)
            if data is not None:
                return _save(data, dest)
    return None


def _save(data, dest):
    """Check a downloaded picture and keep it at `dest`."""
    if not data.startswith(PNG_MAGIC):
        raise DownloadError("The download isn't a picture, so it wasn't used.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
        raise DownloadError(f"The downloaded picture can't be read ({e}).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(data)
    os.replace(part, dest)
    return dest
