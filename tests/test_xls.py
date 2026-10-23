"""Synthetic BIFF8 protocol tests; no private files or xlrd runtime dependency."""
import struct
from dataclasses import replace

import pytest

from legacy_office_parser.errors import (
    EncryptedDocumentError, InvalidDocumentError, LimitExceededError, UnsupportedFormatError,
)
from legacy_office_parser.limits import Limits
from legacy_office_parser.xls import _parse_workbook, _rk, parse_xls_bytes


def rec(code, payload=b''):
    return struct.pack('<HH', code, len(payload)) + payload


def bof(kind=5, version=0x600):
    return rec(0x809, struct.pack('<HHHHII', version, kind, 0, 0, 0, 0))


def string(text):
    data = text.encode('utf-16-le')
    return struct.pack('<HB', len(data) // 2, 1) + data


def cell(code, row=0, col=0, payload=b'', xf=0):
    return rec(code, struct.pack('<HHH', row, col, xf) + payload)


def formula(cache, row=0, col=0):
    return cell(6, row, col, cache + b'\0' * 6 + struct.pack('<H', 1) + b'\x1e')


def special(tag, value=0):
    return bytes([tag, 0, value, 0, 0, 0, 255, 255])


def book(sheets=None, globals=b'', *, physical_order=None):
    if sheets is None:
        sheets = [('Sheet1', 0, b'')]
    bodies = [bof(0x10) + body + rec(0xA) for _, _, body in sheets]
    bounds = [rec(0x85, struct.pack('<IBBB', 0, hidden, 0, len(name)) + b'\0' + name.encode('latin1'))
              for name, hidden, _ in sheets]
    head = bof() + globals
    pos = len(head) + sum(map(len, bounds)) + 4
    offsets = {}
    order = list(range(len(sheets))) if physical_order is None else physical_order
    for index in order:
        offsets[index] = pos
        pos += len(bodies[index])
    bounds = [b[:4] + struct.pack('<I', offsets[i]) + b[8:] for i, b in enumerate(bounds)]
    return head + b''.join(bounds) + rec(0xA) + b''.join(bodies[i] for i in order)


def parse(body=b'', globals=b'', limits=None):
    return _parse_workbook(book([('Sheet1', 0, body)], globals), limits or Limits())


def test_sparse_cells_merges_hidden_and_sheet_order():
    body = cell(0x203, 9, 4, struct.pack('<d', 3.5)) + cell(0x201, 1, 2)
    body += rec(0xE5, struct.pack('<HHHHH', 1, 9, 11, 4, 6))
    doc = _parse_workbook(book([('First', 2, body), ('Second', 0, b'')], physical_order=[1, 0]), Limits())
    assert doc.format == 'xls'
    assert [s.name for s in doc.sheets] == ['First', 'Second']
    sheet = doc.sheets[0]
    assert sheet.hidden and not doc.sheets[1].hidden
    assert [(c.row, c.column, c.value) for c in sheet.cells] == [(2, 3, None), (10, 5, 3.5)]
    assert (sheet.rows, sheet.columns) == (12, 7)
    m = sheet.merges[0]
    assert (m.start_row, m.start_column, m.end_row, m.end_column) == (10, 5, 12, 7)


@pytest.mark.parametrize('number', [-134217728, -1, 0, 123456, 134217727])
def test_rk_signed_integer(number):
    assert _rk(struct.pack('<I', ((number << 2) | 2) & 0xffffffff)) == number


def test_rk_ieee_and_scaled_and_mulrk():
    assert _rk(struct.pack('<I', 0x3ff00000)) == 1.0
    assert _rk(struct.pack('<I', ((-123 << 2) | 3) & 0xffffffff)) == -1.23
    body = cell(0x27e, 0, 0, struct.pack('<I', 0x40000000))
    body += rec(0xbd, struct.pack('<HHHIHIH', 2, 3, 0, 42 * 4 + 2, 0, 123 * 4 + 3, 4))
    body += rec(0xbe, struct.pack('<HHHHH', 5, 7, 0, 0, 8))
    cells = parse(body).sheets[0].cells
    assert [c.value for c in cells] == [2.0, 42, 1.23, None, None]
    assert [(c.row, c.column) for c in cells[-2:]] == [(6, 8), (6, 9)]


def test_sst_changes_encoding_both_directions_and_empty_string():
    sst = rec(0xfc, struct.pack('<IIHB', 3, 3, 5, 0) + b'A\xe9')
    sst += rec(0x3c, b'\x01' + 'Ж'.encode('utf-16-le'))
    sst += rec(0x3c, b'\x00BC' + string('') + string('last'))
    cells = b''.join(cell(0xfd, i, 0, struct.pack('<I', i)) for i in range(3))
    assert [c.value for c in parse(cells, sst).sheets[0].cells] == ['AéЖBC', '', 'last']


def test_sst_rich_runs_phonetic_continuations_have_no_encoding_byte():
    sst = rec(0xfc, struct.pack('<IIHBHi', 2, 2, 1, 0x0c, 1, 5) + b'X')
    sst += rec(0x3c, b'\0\0') + rec(0x3c, b'\0\0abc')
    sst += rec(0x3c, b'de' + string('next'))
    cells = cell(0xfd, 0, 0, struct.pack('<I', 0)) + cell(0xfd, 1, 0, struct.pack('<I', 1))
    assert [c.value for c in parse(cells, sst).sheets[0].cells] == ['X', 'next']


def test_sst_surrogate_pair_across_continuation_and_new_string_boundary():
    sst = rec(0xfc, struct.pack('<IIHB', 2, 2, 2, 1) + b'\x3d\xd8')
    sst += rec(0x3c, b'\x01\x00\xde') + rec(0x3c, string('end'))
    assert parse(cell(0xfd, payload=struct.pack('<I', 0)), sst).sheets[0].cells[0].value == '😀'


def test_formula_all_cache_types_and_intervening_shared_formula():
    body = formula(struct.pack('<d', 42), 0)
    body += formula(special(1, 1), 1) + formula(special(2, 7), 2) + formula(special(3), 3)
    body += formula(special(0), 4) + rec(0x4bc, b'\0' * 10)
    body += rec(0x207, struct.pack('<HB', 4, 0) + b'ab') + rec(0x3c, b'\1c\0d\0')
    doc = parse(body)
    assert [c.value for c in doc.sheets[0].cells] == [42, True, '#DIV/0!', '', 'abcd']
    assert [c.value_type for c in doc.sheets[0].cells] == ['number', 'boolean', 'error', 'string', 'string']
    assert all(c.is_formula and c.formula is None for c in doc.sheets[0].cells)
    assert sum('Formula expressions' in w for w in doc.warnings) == 1


def test_label_and_boolerr():
    body = cell(0x204, payload=string('Привет'))
    body += cell(0x205, 1, 0, b'\0\0') + cell(0x205, 2, 0, b'\x2a\1')
    assert [c.value for c in parse(body).sheets[0].cells] == ['Привет', False, '#N/A']


def xf(fmt):
    return rec(0xe0, struct.pack('<HH', 0, fmt) + b'\0' * 16)


@pytest.mark.parametrize('serial,mode,expected', [(1, 0, '1900-01-01'), (59, 0, '1900-02-28'),
    (61, 0, '1900-03-01'), (0, 1, '1904-01-01'), (1.5, 1, '1904-01-02T12:00:00')])
def test_date_modes(serial, mode, expected):
    c = parse(cell(0x203, payload=struct.pack('<d', serial)), xf(14) + rec(0x22, struct.pack('<H', mode))).sheets[0].cells[0]
    assert c.value_type == 'date' and c.value == expected


def test_custom_date_time_and_ambiguous_dates():
    globals = xf(164) + rec(0x41e, struct.pack('<H', 164) + string('yyyy-mm-dd'))
    assert parse(cell(0x203, payload=struct.pack('<d', 61)), globals).sheets[0].cells[0].text == '1900-03-01'
    assert parse(cell(0x203, payload=struct.pack('<d', .5)), xf(20)).sheets[0].cells[0].text == '12:00:00'
    for serial, fmt in [(60, 14), (-1, 14), (1e200, 14), (1, 165)]:
        doc = parse(cell(0x203, payload=struct.pack('<d', serial)), xf(fmt))
        assert doc.sheets[0].cells[0].value_type == 'number'
        assert doc.warnings


@pytest.mark.parametrize('body', [
    cell(0xfd, payload=struct.pack('<I', 9)),
    formula(special(0)), rec(0x207, string('orphan')),
    formula(special(4)), cell(0x205, payload=b'\2\0'),
    cell(0x203, payload=b'bad'), cell(0x203, payload=struct.pack('<d', float('nan'))),
    cell(0x201, col=256), cell(0x201) + cell(0x201),
    rec(0xbd, struct.pack('<HHH', 0, 5, 4)),
    rec(0xbe, struct.pack('<HHH', 0, 0, 2)),
    rec(0xe5, struct.pack('<HHHHH', 1, 4, 3, 0, 0)),
    rec(0x200, struct.pack('<IIHHH', 0, 65537, 0, 1, 0)),
    ])
def test_malformed_cells(body):
    with pytest.raises(InvalidDocumentError):
        parse(body)


@pytest.mark.parametrize('sst', [
    rec(0xfc, struct.pack('<II', 1, 2)),
    rec(0xfc, struct.pack('<IIHB', 1, 1, 3, 0) + b'a'),
    rec(0xfc, struct.pack('<IIHB', 1, 1, 2, 1) + b'a'),
    rec(0xfc, struct.pack('<II', 1, 1) + b'\x02') + rec(0x3c, b'\0\0ab'),
    rec(0xfc, struct.pack('<IIHBi', 1, 1, 0, 4, -1)),
    rec(0xfc, struct.pack('<IIHB', 1, 1, 1, 1) + b'\0\xd8'),
    ])
def test_malformed_sst(sst):
    with pytest.raises(InvalidDocumentError):
        parse(globals=sst)


def test_encryption_older_biff_truncation_offsets():
    with pytest.raises(EncryptedDocumentError):
        parse(globals=rec(0x2f, b'\0\0'))
    with pytest.raises(UnsupportedFormatError):
        _parse_workbook(bof(version=0x500), Limits())
    data = book()
    for broken in [data[:-1], data[:2], data[:24] + struct.pack('<I', 1) + data[28:]]:
        with pytest.raises(InvalidDocumentError):
            _parse_workbook(broken, Limits())


@pytest.mark.parametrize('limit,body,globals', [
    ({'max_cells': 1}, cell(0x201) + cell(0x201, 1), b''),
    ({'max_records': 2}, b'', b''),
    ({'max_rows': 2}, cell(0x201, 2), b''),
    ({'max_columns': 2}, cell(0x201, col=2), b''),
    ({'max_text_chars': 8}, cell(0x204, payload=string('abc')), b''),
    ({'max_stream_bytes': 8}, b'', b''),
    ({'max_depth': 1}, bof(0x20) + rec(0xa), b''),
    ({'max_cells': 1}, b'', rec(0xfc, struct.pack('<II', 2, 2) + string('') * 2)),
])
def test_limits(limit, body, globals):
    with pytest.raises(LimitExceededError):
        parse(body, globals, replace(Limits(), **limit))


def test_repeated_sst_output_is_text_budgeted():
    sst = rec(0xfc, struct.pack('<II', 3, 1) + string('abc'))
    body = b''.join(cell(0xfd, i, payload=struct.pack('<I', 0)) for i in range(3))
    with pytest.raises(LimitExceededError):
        parse(body, sst, replace(Limits(), max_text_chars=17))


def test_sheet_limit_and_nonworksheet_omission():
    with pytest.raises(LimitExceededError):
        _parse_workbook(book([('A', 0, b''), ('B', 0, b'')]), replace(Limits(), max_sheets=1))
    data = bytearray(book())
    data[29] = 2  # BOUNDSHEET chart kind
    offset = struct.unpack_from('<I', data, 24)[0]
    struct.pack_into('<H', data, offset + 6, 0x20)
    doc = _parse_workbook(bytes(data), Limits())
    assert doc.sheets == [] and doc.warnings


def test_entry_uses_bounded_ole_helpers(monkeypatch):
    from contextlib import contextmanager
    import legacy_office_parser.xls as xls
    class Ole:
        def exists(self, name):
            return name == 'Workbook'
    @contextmanager
    def opened(data, limits):
        assert data == b'test'
        yield Ole()
    def read(ole, name, limits):
        assert name == 'Workbook'
        return book()
    monkeypatch.setattr(xls, 'open_ole', opened)
    monkeypatch.setattr(xls, 'read_stream', read)
    assert parse_xls_bytes(b'test', Limits()).sheets[0].name == 'Sheet1'


def ole_workbook(stream, name='Workbook'):
    """Original minimal CFB writer for a single regular-FAT test stream."""
    free, end = 0xffffffff, 0xfffffffe
    stream = stream.ljust(4096, b'\0')
    count = (len(stream) + 511) // 512
    header = bytearray(512)
    header[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH', header, 24, 0x3e, 3, 0xfffe, 9, 6)
    struct.pack_into('<IIIIIIIII', header, 40, 0, 1, 1, 0, 4096, end, 0, end, 0)
    struct.pack_into('<109I', header, 76, 0, *([free] * 108))
    fat = [free] * 128
    fat[0], fat[1] = 0xfffffffd, end
    for i in range(count):
        fat[2 + i] = 3 + i if i < count - 1 else end
    directory = bytearray(512)
    for i, entry in enumerate(['Root Entry', name]):
        encoded = entry.encode('utf-16le') + b'\0\0'
        at = 128 * i
        directory[at:at + len(encoded)] = encoded
        struct.pack_into('<HBBIII', directory, at + 64, len(encoded), 5 if i == 0 else 2,
                         1, free, free, 1 if i == 0 else free)
        struct.pack_into('<IQ', directory, at + 116, end if i == 0 else 2,
                         0 if i == 0 else len(stream))
    return bytes(header) + struct.pack('<128I', *fat) + directory + stream.ljust(count * 512, b'\0')


@pytest.mark.parametrize('name', ['Workbook', 'Book'])
def test_public_api_synthetic_ole_detection_and_path(tmp_path, name):
    from legacy_office_parser import parse, parse_xls
    data = ole_workbook(book([('Test', 0, cell(0x204, 3, 4, string('Synthetic')))]), name)
    assert parse(data).sheets[0].cells[0].address == 'E4'
    path = tmp_path / 'arbitrary.extension'
    path.write_bytes(data)
    result = parse_xls(path)
    assert result.sheets[0].cells[0].value == 'Synthetic'
    assert 'Synthetic' in result.text
    assert result.to_dict()['sheets'][0]['cells'][0]['row'] == 4


def test_public_api_rejects_encrypted_and_limits():
    from legacy_office_parser import parse_xls
    with pytest.raises(EncryptedDocumentError):
        parse_xls(ole_workbook(book(globals=rec(0x2f))))
    data = ole_workbook(book())
    with pytest.raises(LimitExceededError):
        parse_xls(data, limits=replace(Limits(), max_file_bytes=len(data) - 1))
    with pytest.raises(LimitExceededError):
        parse_xls(data, limits=replace(Limits(), max_stream_bytes=4000))


def test_cells_and_merges_share_one_budget():
    body = cell(0x201) + rec(0xe5, struct.pack('<HHHHH', 1, 0, 0, 0, 1))
    with pytest.raises(LimitExceededError):
        parse(body, limits=replace(Limits(), max_cells=1))


def test_embedded_chart_cells_are_not_worksheet_cells():
    body = bof(0x20) + cell(0x204, payload=string('chart')) + rec(0xa)
    body += cell(0x204, payload=string('worksheet'))
    assert [c.value for c in parse(body).sheets[0].cells] == ['worksheet']


def test_sheet_offset_inside_previous_sheet_and_missing_eof():
    data = bytearray(book([('A', 0, cell(0x201)), ('B', 0, b'')]))
    # The first bound is 13 bytes. Move the second offset into the first body.
    first = struct.unpack_from('<I', data, 24)[0]
    struct.pack_into('<I', data, 37, first + 22)
    with pytest.raises(InvalidDocumentError):
        _parse_workbook(bytes(data), Limits())
    with pytest.raises(InvalidDocumentError):
        _parse_workbook(book()[:-4], Limits())


@pytest.mark.parametrize('fmt', ['mmm hh:mm', 'mmmm hh:mm', 'mm hh:mm', 'm hh:mm', 'hh:mm mmm'])
def test_custom_calendar_month_with_time_preserves_date(fmt):
    globals = xf(164) + rec(0x41e, struct.pack('<H', 164) + string(fmt))
    body = b''.join(cell(0x203, row, payload=struct.pack('<d', serial))
                    for row, serial in enumerate((45000.5, 45031.5)))
    doc = parse(body, globals)
    assert [c.value for c in doc.sheets[0].cells] == [
        '2023-03-15T12:00:00', '2023-04-15T12:00:00',
    ]
    assert all(c.value_type == 'date' and c.text == c.value for c in doc.sheets[0].cells)
    assert not doc.warnings


@pytest.mark.parametrize('fmt', ['hh:mm', 'h:mm:ss', 'mm:ss', 'hh:mm AM/PM'])
def test_custom_time_only_minute_tokens(fmt):
    globals = xf(164) + rec(0x41e, struct.pack('<H', 164) + string(fmt))
    body = b''.join(cell(0x203, row, payload=struct.pack('<d', serial))
                    for row, serial in enumerate((45000.5, 45031.5)))
    doc = parse(body, globals)
    assert [c.value for c in doc.sheets[0].cells] == ['12:00:00', '12:00:00']
    assert all(c.value_type == 'date' for c in doc.sheets[0].cells)
    assert not doc.warnings
