#!/usr/bin/env python3
"""Build an original external-PAPX DOC from the project's authored table fixture.

No parser implementation is used to derive the expected document. The source
Word text and layout are retained; row PAPX groups are relocated into Data and
TDefTable is replaced by explicit insertion/width operations. Developer-only.
"""
from pathlib import Path
import struct

import olefile

ROOT = Path(__file__).resolve().parents[1]
FREE, END, FAT = 0xffffffff, 0xfffffffe, 0xfffffffd


def u16(data, at=0):
    return struct.unpack_from('<H', data, at)[0]


def u32(data, at=0):
    return struct.unpack_from('<I', data, at)[0]


def regular_cfb(streams):
    """Small v3 CFB fixture writer: one FAT, regular streams, balanced directory."""
    names = sorted(streams, key=lambda n: (len(n), n.upper()))
    directory = bytearray(((len(names) + 4) // 4) * 512)
    directory_count = len(directory) // 512
    next_sector = 1 + directory_count
    fat = [FREE] * 128
    fat[0] = FAT
    for sid in range(1, next_sector):
        fat[sid] = sid + 1 if sid + 1 < next_sector else END
    data_parts = []
    for index, name in enumerate(names, 1):
        payload = streams[name].ljust(4096, b'\0')
        count = (len(payload) + 511) // 512
        if next_sector + count > 128:
            raise ValueError('fixture exceeds one FAT sector')
        at = index * 128
        raw_name = name.encode('utf-16le') + b'\0\0'
        directory[at:at + len(raw_name)] = raw_name
        struct.pack_into('<HBBIII', directory, at + 64, len(raw_name), 2, 1, FREE, FREE, FREE)
        struct.pack_into('<IQ', directory, at + 116, next_sector, len(payload))
        for sid in range(next_sector, next_sector + count):
            fat[sid] = sid + 1 if sid + 1 < next_sector + count else END
        data_parts.append(payload.ljust(count * 512, b'\0'))
        next_sector += count
    def tree(indices):
        if not indices:
            return FREE
        middle = len(indices) // 2
        sid = indices[middle]
        struct.pack_into('<II', directory, sid * 128 + 68,
                         tree(indices[:middle]), tree(indices[middle + 1:]))
        return sid
    root = 'Root Entry\0'.encode('utf-16le')
    directory[:len(root)] = root
    struct.pack_into('<HBBIII', directory, 64, len(root), 5, 1, FREE, FREE,
                     tree(list(range(1, len(names) + 1))))
    struct.pack_into('<IQ', directory, 116, END, 0)
    header = bytearray(512)
    header[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH', header, 24, 0x3e, 3, 0xfffe, 9, 6)
    struct.pack_into('<IIIIIIIII', header, 40, 0, 1, 1, 0, 4096, END, 0, END, 0)
    struct.pack_into('<109I', header, 76, 0, *([FREE] * 108))
    return bytes(header) + struct.pack('<128I', *fat) + directory + b''.join(data_parts)


def generate():
    with olefile.OleFileIO(ROOT / 'tests/fixtures/ordinary_table.doc') as ole:
        streams = {path[0]: ole.openstream(path).read() for path in ole.listdir()}
    word = bytearray(streams['WordDocument'])
    table = streams['1Table']
    fc, size = struct.unpack_from('<II', word, 154 + 13 * 8)
    count = (size - 4) // 8
    pages = {u32(table, fc + (count + 1 + i) * 4) & 0x3fffff for i in range(count)}
    data = bytearray()
    replacements = 0
    for page in sorted(pages):
        base = page * 512
        runs = word[base + 511]
        payloads = {}
        for i in range(runs):
            offset = word[base + (runs + 1) * 4 + i * 13] * 2
            if not offset or offset in payloads:
                continue
            at = base + offset
            cb = word[at]
            start, length = (at + 1, cb * 2 - 1) if cb else (at + 2, word[at + 1] * 2)
            group = bytes(word[start + 2:start + length])
            # The authored source has a single unmerged 3-cell TDefTable per row.
            marker = struct.pack('<H', 0xd608)
            pos = group.find(marker)
            if pos < 0:
                payloads[offset] = bytes(word[start:start + length])
                continue
            operand = pos + 2
            n = group[operand + 2]
            assert n == 3
            edges = struct.unpack_from('<4h', group, operand + 3)
            assert edges[0] == 0
            end = operand + u16(group, operand) + 1
            flags = [u16(group, operand + 3 + 8 + j * 20) for j in range(n)]
            assert flags == [0, 0, 0]
            ops = struct.pack('<HBBh', 0x7621, 0, n, 360)
            for j in range(n):
                ops += struct.pack('<HBBh', 0x7623, j, j + 1, edges[j + 1] - edges[j])
            external = group[:pos] + ops + group[end:]
            pointer = struct.pack('<HI', 0x646b, len(data))
            data += struct.pack('<H', len(external)) + external
            # A legacy reader may ignore PTableProps and use this inline fallback.
            # A supporting reader MUST ignore all fallback Prls after the pointer.
            payloads[offset] = bytes(word[start:start + 2]) + pointer + group
            replacements += 1
        front = (runs + 1) * 4 + runs * 13
        rebuilt = bytearray(512)
        rebuilt[:front] = word[base:base + front]
        rebuilt[511] = runs
        cursor = 510
        locations = {}
        for old, payload in payloads.items():
            if len(payload) % 2:
                encoded = bytes([(len(payload) + 1) // 2]) + payload
            else:
                encoded = bytes([0, len(payload) // 2]) + payload
            cursor = (cursor - len(encoded)) & ~1
            assert cursor >= front
            rebuilt[cursor:cursor + len(encoded)] = encoded
            locations[old] = cursor // 2
        for i in range(runs):
            slot = (runs + 1) * 4 + i * 13
            old = word[base + slot] * 2
            if old:
                rebuilt[slot] = locations[old]
        word[base:base + 512] = rebuilt
    assert replacements >= 1
    streams['WordDocument'] = bytes(word)
    streams['Data'] = bytes(data)
    return regular_cfb(streams)


if __name__ == '__main__':
    out = ROOT / 'tests/fixtures/doc_external/ordinary_external.doc'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(generate())
    print(out)
