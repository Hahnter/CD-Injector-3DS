"""Checks on finding NSUI's banner parts inside its program file."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdinjector import nsui_program  # noqa: E402


def _7bit(n):
    out = bytearray()
    while n >= 0x80:
        out.append(n & 0x7F | 0x80)
        n >>= 7
    return bytes(out + bytes([n]))


def resource_table(items):
    """A .NET resource table (as System.Resources.ResourceWriter writes one) holding `items`: [(name, bytes)]."""
    reader = b"System.Resources.ResourceReader, mscorlib"
    kind = b"System.Resources.RuntimeResourceSet"
    header = _7bit(len(reader)) + reader + _7bit(len(kind)) + kind
    out = bytearray(nsui_program.RESOURCES_MAGIC + struct.pack("<II", 1, len(header)) + header)
    out += struct.pack("<iii", 2, len(items), 1) + _7bit(13) + b"System.Byte[]"
    out += (b"PAD" * 3)[:-len(out) % 8]
    names, values, positions, offsets = bytearray(), bytearray(), [], []
    for name, data in items:
        positions.append(len(names))
        encoded = name.encode("utf-16-le")
        names += _7bit(len(encoded)) + encoded + struct.pack("<i", len(values))
        values += _7bit(nsui_program.BYTES) + struct.pack("<i", len(data)) + data
    out += struct.pack("<%di" % len(items), *range(len(items)))           # hashes: not used when reading
    out += struct.pack("<%di" % len(items), *positions)
    out += struct.pack("<i", len(out) + 4 + len(names))
    return bytes(out + names + values)


class ResourceTests(unittest.TestCase):
    def test_resources_are_found_by_name(self):
        table = resource_table([("genesis_cgfx", b"CGFX" + bytes(60)), ("genesis_bcwav", b"CWAV" + bytes(28))])
        program = b"MZ" + bytes(1000) + struct.pack("<i", len(table)) + table + bytes(100)
        found = {name: program[o:o + size] for name, o, size in nsui_program.resources(program)}
        self.assertEqual(found, {"genesis_cgfx": b"CGFX" + bytes(60), "genesis_bcwav": b"CWAV" + bytes(28)})

    def test_a_damaged_table_is_skipped(self):
        table = resource_table([("a", b"x" * 10)])
        for cut in (8, 40, len(table) - 5):
            self.assertEqual(nsui_program.resources(b"MZ" + table[:cut]), [])

    def test_sounds_are_found_with_their_length(self):
        cwav = bytearray(0x80)
        cwav[0:6] = b"CWAV\xff\xfe"
        struct.pack_into("<I", cwav, 0xC, len(cwav))
        cwav[0x40:0x44] = b"INFO"
        struct.pack_into("<5I", cwav, 0x4C, 22050, 0, 44100, 0, 2)
        program = bytes(10) + bytes(cwav) + bytes(10)
        self.assertEqual(nsui_program.sound_spans(program), [(10, 10 + 0x80, 22050, 2, 2.0)])


if __name__ == "__main__":
    unittest.main()
