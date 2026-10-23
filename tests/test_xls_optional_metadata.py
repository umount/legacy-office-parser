"""Optional BIFF metadata does not hide required framing or reference errors."""
import struct

import pytest

from legacy_office_parser import Limits, parse_xls
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.xls import _parse_workbook
from test_xls import book, cell, formula, ole_workbook, rec, special, string


NUMBER = cell(0x203, payload=struct.pack('<d', 7.5))
EMPTY_SST = rec(0xfc, struct.pack('<II', 0, 0))
EMPTY_MERGES = rec(0xe5, b'\0\0')
EMPTY_DIMENSIONS = rec(0x200, bytes(14))


def parse(body=b'', globals=b'', limits=None):
    return parse_xls(ole_workbook(book([('S', 0, body)], globals)), limits=limits or Limits())


@pytest.mark.parametrize('headers,globals', [
    (b'', b''), (b'', EMPTY_SST), (rec(0x14), b''), (rec(0x15), b''),
    (rec(0x14) + rec(0x15), EMPTY_SST),
    (rec(0x14, string('')) + rec(0x15, string('')), EMPTY_SST),
])
def test_absent_or_empty_print_metadata_and_sst_retain_cells(headers, globals):
    doc = parse(headers + NUMBER, globals)
    c, = doc.sheets[0].cells
    assert (c.row, c.column, c.value, c.text) == (1, 1, 7.5, '7.5')
    assert doc.text == 'S\nA1\t7.5'


@pytest.mark.parametrize('body', [b'', EMPTY_DIMENSIONS, EMPTY_MERGES,
                                 EMPTY_DIMENSIONS + EMPTY_MERGES + rec(0x14) + rec(0x15)])
def test_empty_sheet_metadata_does_not_invent_cells(body):
    sheet, = parse(body, EMPTY_SST).sheets
    assert sheet.name == 'S' and sheet.cells == [] and sheet.merges == []
    assert sheet.rows == sheet.columns == 0


@pytest.mark.parametrize('wide', [0, 1])
@pytest.mark.parametrize('text', ['', 'kept'])
def test_zero_length_phonetic_extension_preserves_sst_text(wide, text):
    raw = text.encode('utf-16-le' if wide else 'latin1')
    # fExtSt present with cbExtRst=0 is explicitly permitted by the structure.
    entry = struct.pack('<HBi', len(text), wide | 4, 0) + raw
    sst = rec(0xfc, struct.pack('<II', 1, 1) + entry)
    sheet, = parse(cell(0xfd, payload=bytes(4)), sst).sheets
    c, = sheet.cells
    assert (c.value, c.text, c.value_type) == (text, text, 'string')


def test_blank_formula_cache_has_no_string_dependency():
    doc = parse(formula(special(3)) + cell(0x203, row=1, payload=struct.pack('<d', 7.5)))
    assert [(c.value, c.text, c.is_formula) for c in doc.sheets[0].cells] == [
        ('', '', True), (7.5, '7.5', False)]


@pytest.mark.parametrize('globals', [b'', EMPTY_SST])
def test_missing_or_empty_sst_does_not_satisfy_a_string_reference(globals):
    with pytest.raises(InvalidDocumentError, match='LABELSST index'):
        parse(cell(0xfd, payload=bytes(4)), globals)


@pytest.mark.parametrize('body', [
    rec(0xe5), rec(0xe5, b'\0'), rec(0xe5, b'\1\0'),
    rec(0xe5, b'\0\0' + bytes(8)), rec(0x200, bytes(13)),
    rec(0x200, struct.pack('<IIHHH', 2, 1, 0, 1, 0)),
    rec(0x200, struct.pack('<IIHHH', 0, 65537, 0, 1, 0)),
])
def test_optional_presence_does_not_excuse_bad_counts_or_lengths(body):
    with pytest.raises(InvalidDocumentError):
        parse(body + NUMBER)


@pytest.mark.parametrize('payload', [b'', bytes(7), struct.pack('<II', 0, 1),
                                    bytes(8) + b'x', struct.pack('<II', 1, 1)])
def test_sst_empty_is_not_truncated_or_inconsistent_sst(payload):
    with pytest.raises(InvalidDocumentError):
        parse(NUMBER, rec(0xfc, payload))


@pytest.mark.parametrize('tail', [b'', rec(0x14), NUMBER])
def test_required_formula_string_still_required(tail):
    with pytest.raises(InvalidDocumentError, match='missing formula STRING'):
        parse(formula(special(0)) + tail)


@pytest.mark.parametrize('extra', [-1, 1, 100])
def test_zero_phonetic_length_does_not_relax_nonzero_length_checks(extra):
    entry = struct.pack('<HBi', 1, 4, extra) + b'A'
    with pytest.raises(InvalidDocumentError):
        parse(cell(0xfd, payload=bytes(4)), rec(0xfc, struct.pack('<II', 1, 1) + entry))


def test_empty_optional_records_still_consume_record_budget():
    data = book([('S', 0, rec(0x14) + rec(0x15) + EMPTY_MERGES)], EMPTY_SST)
    # Globals BOF, SST, BOUNDSHEET, EOF, sheet BOF, HEADER, FOOTER, MERGES, EOF.
    assert _parse_workbook(data, Limits(max_records=9)).sheets[0].cells == []
    with pytest.raises(LimitExceededError, match='record limit'):
        _parse_workbook(data, Limits(max_records=8))


def test_optional_empties_do_not_reset_cell_or_text_budget():
    body = NUMBER + rec(0x14) + EMPTY_MERGES + cell(0x203, row=1, payload=struct.pack('<d', 2.5))
    with pytest.raises(LimitExceededError, match='cell limit'):
        parse(body, EMPTY_SST, Limits(max_cells=1))
    # S (1), 7.5 (3), 2.5 (3): optional empty records add no text and reset none.
    assert len(parse(body, EMPTY_SST, Limits(max_text_chars=7)).sheets[0].cells) == 2
    with pytest.raises(LimitExceededError, match='text limit'):
        parse(body, EMPTY_SST, Limits(max_text_chars=6))


@pytest.mark.parametrize('broken', [
    rec(0x14)[:-1], struct.pack('<HH', 0x14, 100) + b'x',
])
def test_ignored_optional_record_requires_complete_outer_framing(broken):
    data = book([('S', 0, NUMBER)])
    # Replace the final EOF with a truncated optional record, without OLE padding.
    with pytest.raises(InvalidDocumentError):
        _parse_workbook(data[:-4] + broken, Limits())


def test_empty_metadata_does_not_make_eof_optional():
    data = book([('S', 0, EMPTY_MERGES)], EMPTY_SST)
    with pytest.raises(InvalidDocumentError, match='missing EOF'):
        _parse_workbook(data[:-4], Limits())
