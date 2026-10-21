#!/usr/bin/env python3
"""Original deterministic conditional table-style visibility DOCs; no production parser imports.

Source: authored ordinary_table.doc. Inline PAPX rebuild follows the existing
identity generator. Preserve stored text, original styles, and cell geometry.
"""

from pathlib import Path
import struct
import olefile
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from generate_doc_external_fixture import regular_cfb, u16, u32  # noqa: E402 - developer fixture helper path

DEST = Path(__file__).resolve().parent
HIDE = struct.pack("<HB", 0x083C, 1)
SHOW = struct.pack("<HB", 0x083C, 0)


def table_style(index, name, base, chpx):
    # StkTableGRLPUPX: TAPX, PAPX (no paragraph-style istd), CHPX.
    raw = bytearray(struct.pack("<5H", 0x1FFE, base << 4 | 3, index << 4 | 3, 0, 0))
    raw += struct.pack("<H", len(name)) + (name + "\0").encode("utf-16le")
    for group in (b"", b"", chpx):
        raw += struct.pack("<H", len(group)) + group + b"\0" * (len(group) & 1)
    struct.pack_into("<H", raw, 6, len(raw))
    return struct.pack("<H", len(raw)) + raw


def generate(mode="header"):
    if mode not in ("disabled", "header", "corner"):
        raise ValueError(mode)
    with olefile.OleFileIO(ROOT / "tests/fixtures/ordinary_table.doc") as ole:
        streams = {p[0]: ole.openstream(p).read() for p in ole.listdir()}
    word = bytearray(streams["WordDocument"])
    table = bytearray(streams["1Table"])

    def append_part(index, data):
        struct.pack_into("<II", word, 154 + index * 8, len(table), len(data))
        table.extend(data)

    fc, size = struct.unpack_from("<II", word, 162)
    styles = bytearray(table[fc : fc + size])
    assert u16(styles, 2) == 16
    struct.pack_into("<H", styles, 2, 18)
    # Header hide followed by top-right show: exact CNFC enums, not masks.
    cnf = struct.pack("<HBH", 0xCA85, 5, 1) + HIDE
    cnf += struct.pack("<HBH", 0xCA85, 5, 0x100) + SHOW
    styles += table_style(16, "FixtureConditionalBase", 0xFFF, cnf)
    styles += table_style(17, "FixtureConditionalChild", 16, b"")
    append_part(1, styles)
    fc, size = struct.unpack_from("<II", word, 154 + 13 * 8)
    count = (size - 4) // 8
    pages = list(
        dict.fromkeys(u32(table, fc + (count + 1 + i) * 4) & 0x3FFFFFFF for i in range(count))
    )
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
            payload = bytes(word[start : start + length])
            group = payload[2:]
            if struct.pack("<H", 0xD608) in group:
                assert struct.pack("<HB", 0x2417, 1) in group
                assert struct.pack("<H", 0x646B) not in group
                assert struct.pack("<H", 0x6646) not in group
                payload += struct.pack("<HH", 0x563A, 17)
                flags = {"disabled": 0x600, "header": 0x620, "corner": 0x720}[mode]
                payload += struct.pack("<HhH", 0x740A, -1, flags)
                row_count += 1
            payloads.append(payload)
        front = (runs + 1) * 4 + runs * 13
        rebuilt = bytearray(512)
        rebuilt[:front] = word[base : base + front]
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
                assert cursor >= front, "PAPX fixture exceeds original FKP capacity"
                rebuilt[cursor : cursor + len(encoded)] = encoded
                locations[payload] = cursor // 2
            rebuilt[(runs + 1) * 4 + i * 13] = locations[payload]
        word[base : base + 512] = rebuilt
    assert row_count == 3
    # Rebuild CHPX runs, preserving original operations. Direct false on alpha
    # beta is the override; direct true on Key is a visibility-control probe.
    fc, size = struct.unpack_from("<II", word, 154 + 12 * 8)
    assert (size - 4) // 8 == 1
    page = u32(table, fc + 8)
    old = word[page * 512 : (page + 1) * 512]
    n = old[511]
    edges = [u32(old, 4 * i) for i in range(n + 1)]
    original = []
    for i in range(n):
        at = old[4 * (n + 1) + i] * 2
        original.append(bytes(old[at + 1 : at + 1 + old[at]]) if at else b"")
    overrides = []
    for token, op in [("alpha beta", SHOW), ("Key", HIDE)]:
        raw = token.encode("utf-16le")
        start = word.find(raw)
        assert start >= 0 and word.find(raw, start + 1) == -1
        overrides.append((start, start + len(raw), op))
    points = sorted(set(edges + [v for a, b, _ in overrides for v in (a, b)]))
    out = bytearray(512)
    cursor = 510
    for i, start in enumerate(points[:-1]):
        source = next(j for j in range(n) if edges[j] <= start < edges[j + 1])
        group = original[source] + b"".join(op for a, b, op in overrides if a <= start < b)
        assert len(group) <= 255
        cursor = (cursor - len(group) - 1) & ~1
        assert cursor >= 4 * len(points) + len(points) - 1
        out[cursor : cursor + len(group) + 1] = bytes([len(group)]) + group
        out[4 * len(points) + i] = cursor // 2
    struct.pack_into("<" + "I" * len(points), out, 0, *points)
    out[511] = len(points) - 1
    word[page * 512 : (page + 1) * 512] = out
    streams.update(WordDocument=bytes(word), **{"1Table": bytes(table), "Data": b""})
    return regular_cfb(streams)


if __name__ == "__main__":
    dest = DEST
    dest.mkdir(parents=True, exist_ok=True)
    for mode in ("disabled", "header", "corner"):
        (dest / (mode + ".doc")).write_bytes(generate(mode))
