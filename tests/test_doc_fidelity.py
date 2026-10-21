"""Compact table properties: expected semantics authored independently of the reader.

MS-DOC 2.9.215 Prm0:
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/35226a0b-9038-4427-83c2-3830a8554267
isprm 0x18 = PFInTable; 0x19 = PFTtp. Bit 0 is zero, bits 1..7
hold isprm, bits 8..15 hold the operand. Literal wire values below are
intentional: no production property decoder generates the expectations.
Reuse only the existing synthetic FIB/CLX/PAPX writer and OLE test adapter.
"""
import pytest

from legacy_office_parser.models import Cell, Paragraph, Table
from test_doc import IN, ROW, definition, fixture, parse


@pytest.mark.parametrize('compressed', [False, True])
def test_compact_membership_recovers_cells_and_empty_coordinates(monkeypatch, compressed):
    streams = fixture([
        ('before\r', compressed),
        ('left\7\7right\7', compressed),
        ('\7', compressed),
        ('after\r', compressed),
    ], props=[b'', b'', b'', b'', ROW + definition([0, 0, 0]), b''],
        prms=[0, 0x0130, 0, 0])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('before'),
                             Table([[Cell('left'), Cell(''), Cell('right')]]),
                             Paragraph('after')]
    assert not any('Prm0' in w or 'without table membership' in w for w in result.warnings)


def test_compact_row_ends_keep_two_rows_instead_of_spurious_cells(monkeypatch):
    streams = fixture([
        ('A\7B\7', True), ('\7', True),
        ('C\7D\7', True), ('\7', True),
    ], props=[IN, IN, IN + definition([0, 0]), IN, IN, IN + definition([0, 0])],
        prms=[0, 0x0132, 0, 0x0132])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Table([[Cell('A'), Cell('B')], [Cell('C'), Cell('D')]])]
    assert not result.warnings


def test_compact_zero_membership_overrides_papx(monkeypatch):
    streams = fixture([('plain\r', True)], props=[IN], prms=[0x0030])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('plain')]
    assert not result.warnings


def test_compact_zero_row_end_overrides_papx(monkeypatch):
    streams = fixture([('A\7', True), ('B\7', True), ('\7', True)],
                      props=[ROW, IN, ROW + definition([0, 0])], prms=[0x0032, 0, 0])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Table([[Cell('A'), Cell('B')]])]
    assert not result.warnings


def test_compact_property_comes_from_piece_containing_paragraph_mark(monkeypatch):
    # The text piece's PFInTable=0 must not override the mark's PFInTable=1.
    streams = fixture([('split', True), ('\7', False), ('\7', True)],
                      props=[b'', ROW + definition([0])], prms=[0x0030, 0x0130, 0])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Table([[Cell('split')]])]
    assert not result.warnings


def test_unimplemented_compact_properties_still_warn(monkeypatch):
    # 0x55 = CFBold, deliberately outside the supported table subset.
    streams = fixture([('plain\r', True)], props=[b''], prms=[0x01AA])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('plain')]
    assert any('Prm0' in w for w in result.warnings)
