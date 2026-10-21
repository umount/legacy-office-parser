#!/usr/bin/env python3
"""Deterministic original DOC identity fixture; inline PAPX, no external fallback.

Derived only from the project's authored ordinary_table.doc. The generic FKP
rebuild below follows generate_doc_external_fixture; no parser code is used.
"""
from pathlib import Path
import struct

import olefile

from generate_doc_external_fixture import regular_cfb, u32

ROOT = Path(__file__).resolve().parents[1]
POSITION = struct.pack('<Hh', 0x940E, 721)


def generate():
    with olefile.OleFileIO(ROOT / 'tests/fixtures/ordinary_table.doc') as ole:
        streams = {path[0]: ole.openstream(path).read() for path in ole.listdir()}
    word = bytearray(streams['WordDocument'])
    table = streams['1Table']
    fc, size = struct.unpack_from('<II', word, 154 + 13 * 8)
    count = (size - 4) // 8
    # Preserve PLC order (logical FC order), rather than physical page order.
    pages = list(dict.fromkeys(u32(table, fc + (count + 1 + i) * 4) & 0x3FFFFF
                               for i in range(count)))
    row_count = 0
    for page in pages:
        base = page * 512
        runs = word[base + 511]
        payloads = []
        for i in range(runs):
            offset = word[base + (runs + 1) * 4 + i * 13] * 2
            if not offset:
                payloads.append(None)
                continue
            at = base + offset
            cb = word[at]
            start, length = (at + 1, cb * 2 - 1) if cb else (at + 2, word[at + 1] * 2)
            payload = bytes(word[start:start + length])
            group = payload[2:]
            if struct.pack('<H', 0xD608) in group:
                assert struct.pack('<HB', 0x2417, 1) in group
                assert struct.pack('<H', 0x646B) not in group
                assert struct.pack('<H', 0x6646) not in group
                if row_count == 0:
                    # Append to the FIRST row's direct properties only. A shared
                    # source PAPX must not make the remaining rows float too.
                    assert struct.pack('<H', 0x940E) not in group
                    payload += POSITION
                row_count += 1
            payloads.append(payload)
        front = (runs + 1) * 4 + runs * 13
        rebuilt = bytearray(512)
        rebuilt[:front] = word[base:base + front]
        rebuilt[511] = runs
        cursor = 510
        locations = {}
        for i, payload in enumerate(payloads):
            if payload is None:
                continue
            if payload not in locations:
                if len(payload) % 2:
                    encoded = bytes([(len(payload) + 1) // 2]) + payload
                else:
                    encoded = bytes([0, len(payload) // 2]) + payload
                cursor = (cursor - len(encoded)) & ~1
                assert cursor >= front, 'PAPX fixture exceeds original FKP capacity'
                rebuilt[cursor:cursor + len(encoded)] = encoded
                locations[payload] = cursor // 2
            rebuilt[(runs + 1) * 4 + i * 13] = locations[payload]
        word[base:base + 512] = rebuilt
    assert row_count == 3
    streams['WordDocument'] = bytes(word)
    # Seven streams give the existing deterministic CFB writer a perfect tree.
    # Empty Data is padding only; no PAPX references it.
    streams['Data'] = b''
    return regular_cfb(streams)


if __name__ == '__main__':
    destination = ROOT / 'tests/fixtures/doc_identity/first_row_position.doc'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(generate())
    print(destination)
