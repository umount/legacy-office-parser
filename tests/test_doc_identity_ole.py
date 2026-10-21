"""Exact public-API oracle for an original inline-PAPX OLE fixture."""
from pathlib import Path
import struct
import sys

import olefile

from legacy_office_parser import parse_doc
from legacy_office_parser.models import Cell, Paragraph, Table

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/doc_identity/first_row_position.doc'


def test_public_api_exact_structure_and_text():
    expected = [
        Paragraph('Synthetic document / Синтетический документ'),
        Table([[Cell('Key'), Cell('Value'), Cell('Примечание')]]),
        Table([[Cell('alpha beta'), Cell(''), Cell('два слова')],
               [Cell(''), Cell('42'), Cell('English and русский')]]),
        Paragraph('After table / После таблицы'),
    ]
    result = parse_doc(FIXTURE)
    assert result.blocks == expected
    assert result.text == (
        'Synthetic document / Синтетический документ\n\n'
        'Key\tValue\tПримечание\n\n'
        'alpha beta\t\tдва слова\n\t42\tEnglish and русский\n\n'
        'After table / После таблицы'
    )
    assert not (result.slides or result.sheets or result.footnotes or result.endnotes
                or result.headers_footers or result.textboxes)
    assert result.warnings == [
        'Preferred table widths and automatic table layout are not evaluated; '
        'explicit cell geometry is used.'
    ]


def test_generator_reproduces_bytes():
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from generate_doc_identity_fixture import generate
        assert generate() == generate() == FIXTURE.read_bytes()
    finally:
        sys.path.pop(0)


def test_first_row_only_has_inline_position():
    with olefile.OleFileIO(FIXTURE) as ole:
        word = ole.openstream('WordDocument').read()
        table = ole.openstream('1Table').read()
        assert set(ole.openstream('Data').read()) <= {0}
    fc, size = struct.unpack_from('<II', word, 154 + 13 * 8)
    count = (size - 4) // 8
    rows = []
    for i in range(count):
        page = struct.unpack_from('<I', table, fc + 4 * (count + 1 + i))[0] & 0x3FFFFF
        base = page * 512
        runs = word[base + 511]
        for j in range(runs):
            off = word[base + (runs + 1) * 4 + j * 13] * 2
            if not off:
                continue
            at = base + off
            cb = word[at]
            start, n = (at + 1, cb * 2 - 1) if cb else (at + 2, word[at + 1] * 2)
            group = word[start + 2:start + n]
            assert b'\x6b\x64' not in group and b'\x46\x66' not in group
            if b'\x08\xd6' in group:
                rows.append(group)
    assert len(rows) == 3
    assert rows[0].endswith(struct.pack('<Hh', 0x940E, 721))
    assert all(b'\x0e\x94' not in group for group in rows[1:])
