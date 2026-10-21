"""Section marks terminate paragraphs; manual page breaks do not (MS-DOC 2.8.26)."""
from pathlib import Path

import pytest

from legacy_office_parser import parse_doc
from legacy_office_parser.doc import _Budget, _Doc
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from test_doc import IN, ROW, fixture, parse, u32


def with_sections(streams, cps=None, raw=None):
    if raw is None:
        # Only the PLC's CPs matter here; SEPX layout is deliberately not read.
        raw = b''.join(u32(cp) for cp in cps) + b'\0\0\xff\xff\xff\xff\0\0\0\0\0\0' * (len(cps) - 1)
    table_name = '1Table' if '1Table' in streams else '0Table'
    table = streams[table_name]
    word = bytearray(streams['WordDocument'])
    word[154 + 6 * 8:162 + 6 * 8] = u32(len(table)) + u32(len(raw))
    return {**streams, 'WordDocument': bytes(word), table_name: table + raw}


def section_fixture(text, props, cps):
    # The common helper recognizes CR/cell marks for synthetic PAPX. Preserve
    # their CPs/FCs while changing only the intended text characters back to FF.
    streams = fixture([(text.replace('\f', '\r'), True)], props=props)
    word = bytearray(streams['WordDocument'])
    word[1024:1024 + len(text)] = text.encode('latin1')
    streams['WordDocument'] = bytes(word)
    return with_sections(streams, cps)


def test_section_before_table_uses_its_own_paragraph_properties(monkeypatch):
    out = parse(monkeypatch, section_fixture('one\ftwo\fcell\7\7',
                                            [b'', b'', IN, ROW], [0, 4, 8, 14]))
    assert out.blocks[:2] == [Paragraph('one'), Paragraph('two')]
    assert isinstance(out.blocks[2], Table)
    assert out.blocks[2].rows[0][0].text == 'cell'
    assert not out.warnings


@pytest.mark.parametrize('sections', [None, [0, 4]])
def test_manual_page_break_stays_in_paragraph(monkeypatch, sections):
    streams = fixture([('a\fb\r', True)])
    if sections:
        streams = with_sections(streams, sections)
    assert parse(monkeypatch, streams).blocks == [Paragraph('a\nb')]


def test_page_and_section_breaks_are_distinguished(monkeypatch):
    out = parse(monkeypatch, with_sections(fixture([('a\fb\fc\r', True)]), [0, 4, 6]))
    assert out.blocks == [Paragraph('a\nb'), Paragraph('c')]


def test_manual_page_break_does_not_end_table_cell(monkeypatch):
    streams = fixture([('a\fb\7\7', True)], props=[IN, ROW])
    out = parse(monkeypatch, with_sections(streams, [0, 5]))
    assert len(out.blocks) == 1
    assert out.blocks[0].rows[0][0].text == 'a\nb'
    assert not out.warnings


def test_section_cps_are_utf16_units_across_pieces(monkeypatch):
    streams = fixture([('a', True), ('😀\f', False), ('b\r', True)])
    out = parse(monkeypatch, with_sections(streams, [0, 4, 6]))
    assert out.blocks == [Paragraph('a😀'), Paragraph('b')]


def test_final_sentinel_does_not_split_auxiliary_story(monkeypatch):
    # The sentinel can extend past the main story, even ending at an aux FF.
    streams = fixture([('a\fb\rnote\frest\r', True)], counts=[4, 10, 0, 0, 0, 0, 0])
    out = parse(monkeypatch, with_sections(streams, [0, 2, 9]))
    assert out.blocks == [Paragraph('a'), Paragraph('b')]
    assert out.footnotes == 'note\nrest'


@pytest.mark.parametrize('cps', [[0], [0, 1]])
def test_empty_main_story_with_section_plc(monkeypatch, cps):
    streams = fixture([('note\r', True)], counts=[0, 5, 0, 0, 0, 0, 0])
    out = parse(monkeypatch, with_sections(streams, cps))
    assert out.blocks == []
    assert out.footnotes == 'note'


@pytest.mark.parametrize('cps', [
    [1, 4], [0, 2, 2, 4], [0, 3, 2, 4], [0, 2, 3],
    [0, 4, 5], [0, 1, 4], [0, 0x7fffffff], [0, 0x80000000], [0],
])
def test_invalid_section_boundaries_are_rejected(monkeypatch, cps):
    with pytest.raises(InvalidDocumentError, match='section'):
        parse(monkeypatch, with_sections(fixture([('a\fb\r', True)]), cps))


@pytest.mark.parametrize('raw', [b'\0', b'\0' * 19, b'\0' * 21])
def test_invalid_section_plc_size(monkeypatch, raw):
    with pytest.raises(InvalidDocumentError, match='section PLC size'):
        parse(monkeypatch, with_sections(fixture([('a\r', True)]), raw=raw))


def test_section_count_is_budgeted_before_reading_cps():
    owner = _Doc.__new__(_Doc)
    owner.budget = _Budget(Limits(max_records=1))
    # Two SEDs: the budget must reject before these invalid CPs are examined.
    owner.table_part = lambda index: b'\0' * 36
    with pytest.raises(LimitExceededError, match='record'):
        owner._sections()
    assert not owner.section_ends


def test_clean_converted_section_before_table():
    from legacy_office_parser._ole import open_ole
    path = Path(__file__).parent / 'fixtures/doc_sections/clean_section_before_table.doc'
    # Guard against a converter optimizing away identical section properties:
    # this fixture must exercise a real PLCSED-backed U+000C boundary.
    with open_ole(path.read_bytes(), Limits()) as ole:
        assert _Doc(ole, Limits()).section_ends == {32}
    out = parse_doc(path)
    assert out.blocks == [Paragraph('First paragraph'), Paragraph('Second paragraph'),
                          Table([[Cell('Left'), Cell('Right')]]), Paragraph('After table')]
    assert not out.warnings


def test_benign_converted_sections_before_table():
    out = parse_doc(Path(__file__).parent / 'fixtures/doc_sections/sections_before_table.doc')
    assert all(isinstance(block, Paragraph) for block in out.blocks[:20])
    assert all(block.text.startswith(f'Paragraph{i:06d}') for i, block in enumerate(out.blocks[:20]))
    tables = [block for block in out.blocks if isinstance(block, Table)]
    cells = [cell for table in tables for row in table.rows for cell in row]
    assert len(cells) == 60
    assert all(cell.text.startswith(f'Table{i:06d}') for i, cell in enumerate(cells))
    assert all('Paragraph' not in cell.text for cell in cells)
    # Conversion also placed out-of-table section marks between cells. Do not
    # silently invent one continuous table across those explicit boundaries.
    assert any('without a row terminator' in warning for warning in out.warnings)
