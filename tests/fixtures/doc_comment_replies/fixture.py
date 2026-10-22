"""Original reply records applied to our original three-comment CFB fixture.

No production parser imports. Equal-sized stream writes preserve all unrelated
CFB bytes. The XML source documents text only, not the authored reply metadata.
"""
import json
from pathlib import Path
import shutil
import struct

import olefile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'doc_comments/authored.doc'


def location(word):
    at = 32
    at += 2 + 2 * struct.unpack_from('<H', word, at)[0]
    at += 2 + 4 * struct.unpack_from('<H', word, at)[0]
    assert struct.unpack_from('<H', word, at)[0] > 112
    return struct.unpack_from('<II', word, at + 2 + 112 * 8)


def generate(destination):
    shutil.copyfile(SOURCE, destination)
    with olefile.OleFileIO(destination, write_mode=True) as compound:
        word = compound.openstream('WordDocument').read()
        offset, size = location(word)
        assert size == 54
        table = bytearray(compound.openstream('1Table').read())
        # One explicit root, its reply, and that reply's child. Preserve dates.
        for i, (depth, parent) in enumerate(((0, 0), (1, -1), (2, -1))):
            struct.pack_into('<IiI', table, offset + i * 18 + 6, depth, parent, 0)
        compound.write_stream('1Table', bytes(table))


def inspect(path):
    with olefile.OleFileIO(path) as compound:
        word = compound.openstream('WordDocument').read()
        table = compound.openstream('1Table').read()
    offset, size = location(word)
    assert size % 18 == 0
    records = []
    for i in range(size // 18):
        depth, relative, flags = struct.unpack_from('<IiI', table, offset + i * 18 + 6)
        records.append({'ordinal': i + 1, 'depth': depth, 'relative_parent': relative,
                        'parent_ordinal': i + relative + 1 if depth else None,
                        'flags': flags})
    return records


if __name__ == '__main__':
    generate(ROOT / 'authored.doc')
    print(json.dumps(inspect(ROOT / 'authored.doc'), indent=2))
