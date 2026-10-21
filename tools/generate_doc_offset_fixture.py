#!/usr/bin/env python3
"""Original unequal-row DOC: change only one explicit boundary in authored data."""
from pathlib import Path
import struct

import olefile

from generate_doc_external_fixture import regular_cfb

ROOT = Path(__file__).resolve().parents[1]


def generate():
    with olefile.OleFileIO(ROOT / 'tests/fixtures/ordinary_table.doc') as ole:
        streams = {p[0]: ole.openstream(p).read() for p in ole.listdir()}
    word = bytearray(streams['WordDocument'])
    table = streams['1Table']
    fc, size = struct.unpack_from('<II', word, 154 + 13 * 8)
    count = (size - 4) // 8
    pages = sorted({struct.unpack_from('<I', table, fc + (count + 1 + i) * 4)[0]
                    & 0x3fffff for i in range(count)})
    changed = False
    for page in pages:
        base = page * 512
        runs = word[base + 511]
        for i in range(runs):
            at = base + word[base + (runs + 1) * 4 + i * 13] * 2
            cb = word[at]
            start, length = (at + 1, cb * 2 - 1) if cb else (at + 2, word[at + 1] * 2)
            group = bytes(word[start + 2:start + length])
            pos = group.find(struct.pack('<H', 0xd608))
            if pos < 0:
                continue
            operand = start + 2 + pos + 2
            assert word[operand + 2] == 3
            assert struct.unpack_from('<h', word, operand + 3)[0] == 0
            # Only the first source row starts 100 twips later. All other edges,
            # cell marks, text and inline properties are retained verbatim.
            struct.pack_into('<h', word, operand + 3, 100)
            changed = True
            break
        if changed:
            break
    assert changed
    streams['WordDocument'] = bytes(word)
    streams['Data'] = b''  # Seven streams give the fixture writer a perfect directory tree.
    return regular_cfb(streams)


if __name__ == '__main__':
    destination = ROOT / 'tests/fixtures/doc_offsets/offset_rows.doc'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(generate())
    print(destination)
