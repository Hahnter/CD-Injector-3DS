"""Finding the parts NSUI's own banners are made of inside its program file.

NSUI (New Super Ultimate Injector for 3DS) is a .NET program that keeps its banner templates, 3D models and banner
sounds as resources inside "New Super Ultimate Injector for 3DS.exe". This module reads a copy of that file the user
already has and finds them there: nothing from NSUI comes with this app.

A .NET resource table (a ".resources" stream) is: a header (magic 0xBEEFCACE), the number of resources and their
type names, padding to 8 bytes, a hash and a name offset per resource, the offset of the data section, the names
(UTF-16, each followed by its value's offset in the data section) and the data section. A byte array value is a
type code (0x20, or 0x21 for a stream) and a 32-bit length before its bytes.
"""

import struct

RESOURCES_MAGIC = b"\xce\xca\xef\xbe"
MAX_RESOURCES = 100000
BYTES, STREAM = 0x20, 0x21


def _7bit(d, p):
    """A 7-bit encoded length (as .NET writes it) at d[p:]: (value, next position)."""
    n = shift = 0
    while True:
        b = d[p]
        p += 1
        n |= (b & 0x7F) << shift
        if b < 0x80:
            return n, p
        shift += 7
        if shift > 28:
            raise ValueError("bad length")


def _table(d, base):
    """[(name, data offset, size)] for each byte-array or stream resource in the resource table at d[base:]."""
    _magic, header_version, skip = struct.unpack_from("<III", d, base)
    if header_version != 1 or skip > 4096:
        return []
    p = base + 12 + skip
    version, count, n_types = struct.unpack_from("<iii", d, p)
    p += 12
    if version != 2 or not 0 < count <= MAX_RESOURCES or not 0 <= n_types <= 1000:
        return []
    for _ in range(n_types):
        n, p = _7bit(d, p)
        p += n
    p += -(p - base) % 8                                  # "PAD" up to a multiple of 8
    positions = struct.unpack_from("<%di" % count, d, p + 4 * count)
    p += 8 * count
    data_section = base + struct.unpack_from("<i", d, p)[0]
    names = p + 4
    out = []
    for pos in positions:
        q = names + pos
        n, q = _7bit(d, q)
        if n > 1024:
            raise ValueError("bad name")
        name = bytes(d[q:q + n]).decode("utf-16-le")
        value = data_section + struct.unpack_from("<i", d, q + n)[0]
        code, v = _7bit(d, value)
        if code in (BYTES, STREAM):
            size = struct.unpack_from("<i", d, v)[0]
            if 0 <= size and v + 4 + size <= len(d):
                out.append((name, v + 4, size))
    return out


def resources(data):
    """[(name, offset, size)] for every byte-array or stream resource in every .NET resource table in `data`."""
    out = []
    at = data.find(RESOURCES_MAGIC)
    while at >= 0:
        try:
            out += _table(data, at)
        except (ValueError, IndexError, struct.error, UnicodeDecodeError):
            pass
        at = data.find(RESOURCES_MAGIC, at + 4)
    return out


def sound_spans(data):
    """[(start, end, sample rate, channels, seconds)] for each 3DS banner sound (CWAV) in `data`."""
    out = []
    at = data.find(b"CWAV\xff\xfe")
    while at >= 0:
        try:
            size = struct.unpack_from("<I", data, at + 0xC)[0]
            if 0x60 <= size <= 4 * 1024 * 1024 and at + size <= len(data) and data[at + 0x40:at + 0x44] == b"INFO":
                rate, _loop_start, samples, _reserved, channels = struct.unpack_from("<5I", data, at + 0x4C)
                if 0 < rate <= 192000:
                    out.append((at, at + size, rate, channels, samples / rate))
        except struct.error:
            pass
        at = data.find(b"CWAV\xff\xfe", at + 4)
    return out
