"""Compact table properties: expected semantics authored independently of the reader.

MS-DOC 2.9.215 Prm0:
https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/35226a0b-9038-4427-83c2-3830a8554267
isprm 0x18 = PFInTable; 0x19 = PFTtp. Bit 0 is zero, bits 1..7
hold isprm, bits 8..15 hold the operand. Literal wire values below are
intentional: no production property decoder generates the expectations.
Reuse only the existing synthetic FIB/CLX/PAPX writer and OLE test adapter.
"""
import struct

import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits

from legacy_office_parser.models import Cell, Paragraph, Table
from test_doc import IN, ROW, definition, fixture, mutate, parse, sprm, u16, u32


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


# MS-DOC 2.9.33 ChpxFkp, 2.9.47 CSymbolOperand, 2.9.82 FFN,
# 2.9.286 SttbfFfn. All streams below are authored here; no private bytes.


def append_table_part(streams, index, data):
    offset = len(streams['1Table'])
    streams['1Table'] += data
    mutate(streams, 'WordDocument', 154 + index * 8, u32(offset) + u32(len(data)))


def add_fonts(streams, fonts=(('Wingdings', 2),)):
    records = []
    for name, charset in fonts:
        # FFN excludes its byte-sized length prefix. No alternate name.
        raw = b'\0' + u16(400) + bytes([charset, 0]) + b'\0' * 34
        raw += (name + '\0').encode('utf-16le')
        records.append(bytes([len(raw)]) + raw)
    append_table_part(streams, 15, u16(len(records)) + u16(0) + b''.join(records))


def add_chpx(streams, fcs, groups):
    """Independent one-page CHPX writer, with real exclusive FC boundaries."""
    assert len(fcs) == len(groups) + 1
    page = bytearray(512)
    page[:4 * len(fcs)] = b''.join(map(u32, fcs))
    pos = (4 * len(fcs) + len(groups) + 1) & ~1
    shared = {}
    for i, group in enumerate(groups):
        if group is None:
            continue  # zero rgb means no CHPX
        if group not in shared:
            shared[group] = pos
            page[pos:pos + 1 + len(group)] = bytes([len(group)]) + group
            pos = (pos + 1 + len(group) + 1) & ~1
        page[4 * len(fcs) + i] = shared[group] // 2
    assert pos < 511
    page[511] = len(groups)
    word = streams['WordDocument']
    assert len(word) % 512 == 0
    pn = len(word) // 512
    streams['WordDocument'] = word + page
    mutate(streams, 'WordDocument', 64, u32(len(word) + 512))
    append_table_part(streams, 12, u32(fcs[0]) + u32(fcs[-1]) + u32(pn))
    return pn * 512


def symbol(code, font=0):
    # Literal opcode and little-endian ftc/xchar, not a production encoder.
    return b'\x09\x6a' + struct.pack('<HH', font, code)


def symbol_fixture(text='(\r', group=None, *, compressed=True, fonts=(('Wingdings', 2),),
                   prcs=(), prms=None):
    streams = fixture([(text, compressed)], prcs=prcs, prms=prms)
    size = len(text.encode('utf-16le')) // 2
    add_chpx(streams, [1024, 1024 + size * (1 if compressed else 2)],
             [symbol(0xF0E0) if group is None else group])
    if fonts is not None:
        add_fonts(streams, fonts)
    return streams


@pytest.mark.parametrize('compressed', [True, False])
def test_symbol_codes_replace_only_their_own_chpx_run(monkeypatch, compressed):
    text = '( x ( y (\r'
    width = 1 if compressed else 2
    streams = fixture([(text, compressed)])
    add_chpx(streams, [1024 + width * cp for cp in (0, 1, 4, 5, 8, len(text))],
             [symbol(0xF0E0), None, symbol(0xF0DF), None, None])
    add_fonts(streams)
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('\uf0e0 x \uf0df y (')]
    assert sum('no font-specific Unicode glyph mapping' in w for w in result.warnings) == 1


@pytest.mark.parametrize('code', [0x03A9, 0x0416, 0x20AC, 0x2192, 0x0080, 0x00E0])
def test_xchar_is_unicode_even_with_a_legacy_font_charset(monkeypatch, code):
    # chs=204 is Russian; xchar is still Unicode, never CP1251 or CP1252.
    result = parse(monkeypatch, symbol_fixture(group=symbol(code), fonts=(('Test', 204),)))
    assert result.blocks == [Paragraph(chr(code))]
    assert not any('glyph mapping' in w for w in result.warnings)


@pytest.mark.parametrize('font,charset', [('Symbol', 0), ('Wingdings', 0), ('Test', 2)])
def test_font_dependent_non_pua_codes_are_retained_with_warning(monkeypatch, font, charset):
    result = parse(monkeypatch, symbol_fixture(group=symbol(0x41), fonts=((font, charset),)))
    assert result.blocks == [Paragraph('A')]
    assert any('glyph mapping' in w for w in result.warnings)


def test_symbol_lookup_keeps_utf16_cp_after_astral_and_invalid_units(monkeypatch):
    result = parse(monkeypatch, symbol_fixture('😀(\r', compressed=False))
    assert result.blocks == [Paragraph('😀\uf0e0')]
    streams = fixture([(b'\x00\xd8(\0\r\0', False)])
    add_chpx(streams, [1024, 1026, 1030], [None, symbol(0x2192)])
    add_fonts(streams, [('Test', 0)])
    assert parse(monkeypatch, streams).blocks == [Paragraph('\ufffd→')]


def test_prc_symbol_overrides_chpx_without_leaking_to_next_piece(monkeypatch):
    streams = fixture([('(', True), ('(\r', False)],
                      prcs=[symbol(0x2190)], prms=[1, 0])
    add_chpx(streams, [1024, 1045], [symbol(0x2192)])
    add_fonts(streams, [('Test', 0)])
    assert parse(monkeypatch, streams).blocks == [Paragraph('←→')]


def test_last_csymbol_wins_and_style_resets_preserve_it(monkeypatch):
    group = symbol(0x2190) + symbol(0x2192) + sprm(0x2A33, 0) + sprm(0x4A30, u16(10))
    result = parse(monkeypatch, symbol_fixture(group=group, fonts=(('Test', 0),)))
    assert result.blocks == [Paragraph('→')]


@pytest.mark.parametrize('prc,prm,expected', [
    (sprm(0x0855, 0), 1, '('),
    (sprm(0x0855, 0) + sprm(0x0855, 1), 1, '\uf0e0'),
    (b'', 0x00EA, '('),  # Prm0 0x75 CFSpec=0
    (b'', 0x01EA, '\uf0e0'),
])
def test_cfspec_overlays_can_disable_or_enable_symbol(monkeypatch, prc, prm, expected):
    result = parse(monkeypatch, symbol_fixture(prcs=[prc], prms=[prm]))
    assert result.blocks == [Paragraph(expected)]


@pytest.mark.parametrize('value', [128, 129])
def test_style_relative_cfspec_is_explicitly_unresolved(monkeypatch, value):
    result = parse(monkeypatch, symbol_fixture(group=symbol(0xF0E0) + sprm(0x0855, value)))
    assert result.blocks == [Paragraph('\uf0e0')]
    assert any('Style-relative CFSpec' in w for w in result.warnings)


def test_piece_symbol_without_chpx_and_unformatted_parenthesis(monkeypatch):
    streams = fixture([('(\r', True)], prcs=[symbol(0x2192)], prms=[1])
    add_fonts(streams, [('Test', 0)])
    assert parse(monkeypatch, streams).blocks == [Paragraph('→')]
    assert parse(monkeypatch, fixture([('(\r', True)])).blocks == [Paragraph('(')]


def test_fc_lookup_follows_reordered_pieces(monkeypatch):
    streams = fixture([('(', True), ('(', True), ('\r', True)])
    add_chpx(streams, [1024, 1025, 1041, 1042, 1059],
             [symbol(0x2190), None, symbol(0x2192), None])
    add_fonts(streams, [('Test', 0)])
    # CLX: 5-byte Pcdt header, 4 CPs, then 8-byte PCD records.
    mutate(streams, '1Table', 23, u32(0x40000000 | 1041 * 2))
    mutate(streams, '1Table', 31, u32(0x40000000 | 1024 * 2))
    assert parse(monkeypatch, streams).blocks == [Paragraph('→←')]


def test_fields_filter_instructions_before_symbol_substitution(monkeypatch):
    text = '\x13(\x14(\x15(\r'
    result = parse(monkeypatch, symbol_fixture(text, group=symbol(0x2192), fonts=(('Test', 0),)))
    assert result.blocks == [Paragraph('→→')]


@pytest.mark.parametrize('code', [0x0007, 0x000D, 0x0013])
def test_symbol_code_is_not_reinterpreted_as_a_structure_delimiter(monkeypatch, code):
    result = parse(monkeypatch, symbol_fixture('(end\r', group=symbol(code)))
    assert result.blocks == [Paragraph(chr(code) + 'end')]
    assert not any('Unbalanced' in w for w in result.warnings)


@pytest.mark.parametrize('code', [0xD800, 0xDFFF])
def test_invalid_symbol_surrogates_are_replaced_explicitly(monkeypatch, code):
    result = parse(monkeypatch, symbol_fixture(group=symbol(code)))
    assert result.blocks == [Paragraph('\ufffd')]
    assert any('Invalid symbol Unicode' in w for w in result.warnings)


def test_symbol_codes_in_auxiliary_stories(monkeypatch):
    streams = fixture([('B\r(\r(\r', True)], counts=[2, 2, 2, 0, 0, 0, 0])
    add_chpx(streams, [1024, 1030], [symbol(0x2192)])
    add_fonts(streams, [('Test', 0)])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('B')]
    assert result.footnotes == result.headers_footers == '→'


def test_missing_font_table_retains_code_with_warning(monkeypatch):
    result = parse(monkeypatch, symbol_fixture(fonts=None))
    assert result.blocks == [Paragraph('\uf0e0')]
    assert any('font table is absent' in w for w in result.warnings)


def test_missing_font_reference_is_structured_error(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='missing font'):
        parse(monkeypatch, symbol_fixture(group=symbol(0x2192, font=1)))


@pytest.mark.parametrize('offset,value', [(511, b'\0'), (511, b'\x66'), (8, b'\1'),
                                         (4, u32(1024))])
def test_malformed_chpx_page_is_structured_error(monkeypatch, offset, value):
    streams = symbol_fixture()
    page = len(streams['WordDocument']) - 512
    mutate(streams, 'WordDocument', page + offset, value)
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, streams)


def test_truncated_symbol_operand_is_structured_error(monkeypatch):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, symbol_fixture(group=b'\x09\x6a\0\0\xe0'))


def test_font_table_validation(monkeypatch):
    for data in (b'\1', u16(1) + u16(1), u16(0x7FF1) + u16(0),
                 u16(1) + u16(0) + b'\xff', u16(1) + u16(0) + b'\0'):
        streams = symbol_fixture(fonts=None)
        append_table_part(streams, 15, data)
        with pytest.raises(InvalidDocumentError):
            parse(monkeypatch, streams)


@pytest.mark.parametrize('budget', [96, 97, 98])
def test_symbol_run_sprm_and_font_records_share_budget(monkeypatch, budget):
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, symbol_fixture(), Limits(max_records=budget))


def test_repeated_symbols_reuse_run_and_font_decoding(monkeypatch):
    text = '(' * 1000 + '\r'
    result = parse(monkeypatch, symbol_fixture(text), Limits(max_records=100, max_text_chars=1001))
    assert result.blocks == [Paragraph('\uf0e0' * 1000)]


def test_chpx_operand_cannot_include_the_final_crun_byte(monkeypatch):
    streams = symbol_fixture()
    page = len(streams['WordDocument']) - 512
    mutate(streams, 'WordDocument', page + 8, b'\xff')
    mutate(streams, 'WordDocument', page + 510, b'\x01')
    with pytest.raises(InvalidDocumentError, match='offset or size'):
        parse(monkeypatch, streams)


def test_zero_size_chpx_at_last_available_byte_is_valid(monkeypatch):
    streams = symbol_fixture()
    page = len(streams['WordDocument']) - 512
    mutate(streams, 'WordDocument', page + 8, b'\xff')
    assert parse(monkeypatch, streams).blocks == [Paragraph('(')]


def test_present_empty_font_table_does_not_claim_a_valid_font(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='missing font'):
        parse(monkeypatch, symbol_fixture(fonts=()))


def test_chpx_bin_does_not_reuse_last_run_beyond_its_end(monkeypatch):
    streams = fixture([('x(\r', True)])
    add_chpx(streams, [1024, 1025], [symbol(0x2192)])
    add_fonts(streams, [('Test', 0)])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('x(')]
    assert any('no CHPX coverage' in w for w in result.warnings)


def test_chpx_page_must_cover_character_inside_its_bin(monkeypatch):
    streams = symbol_fixture()
    page = len(streams['WordDocument']) - 512
    mutate(streams, 'WordDocument', page, u32(1025))
    with pytest.raises(InvalidDocumentError, match='does not cover'):
        parse(monkeypatch, streams)


def test_bad_character_bin_page_and_size(monkeypatch):
    for plc in (b'\0', u32(1024) + u32(1024) + u32(9),
                u32(1024) + u32(1026) + u32(0x3FFFFF)):
        streams = symbol_fixture()
        append_table_part(streams, 12, plc)
        with pytest.raises(InvalidDocumentError):
            parse(monkeypatch, streams)


def test_invalid_cfspec_toggle(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='CFSpec'):
        parse(monkeypatch, symbol_fixture(group=symbol(0x2192) + sprm(0x0855, 2)))


def test_font_alternate_name_is_validated_but_not_used_as_a_mapping(monkeypatch):
    streams = symbol_fixture(fonts=None)
    raw = b'\0' + u16(400) + bytes([2, 5]) + b'\0' * 34
    raw += 'Test\0Symbol\0'.encode('utf-16le')
    append_table_part(streams, 15, u16(1) + u16(0) + bytes([len(raw)]) + raw)
    assert parse(monkeypatch, streams).blocks == [Paragraph('\uf0e0')]
    at = struct.unpack_from('<I', streams['WordDocument'], 154 + 15 * 8)[0]
    mutate(streams, '1Table', at + 9, b'\x04')
    with pytest.raises(InvalidDocumentError, match='alternate index'):
        parse(monkeypatch, streams)


def test_symbol_fkp_across_two_pages(monkeypatch):
    streams = fixture([('((\r', True)])
    first = add_chpx(streams, [1024, 1025], [symbol(0x2190)]) // 512
    second = add_chpx(streams, [1025, 1027], [symbol(0x2192)]) // 512
    append_table_part(streams, 12, b''.join(map(u32, [1024, 1025, 1027, first, second])))
    add_fonts(streams, [('Test', 0)])
    assert parse(monkeypatch, streams).blocks == [Paragraph('←→')]


def test_piece_cfspec_reenables_a_chpx_symbol(monkeypatch):
    streams = symbol_fixture(group=symbol(0x2192) + sprm(0x0855, 0),
                             prcs=[sprm(0x0855, 1)], prms=[1], fonts=(('Test', 0),))
    assert parse(monkeypatch, streams).blocks == [Paragraph('→')]


def test_shared_fkp_group_is_charged_once_but_all_runs_are_charged(monkeypatch):
    streams = fixture([('((\r', True)])
    add_chpx(streams, [1024, 1025, 1027], [symbol(0x2192), symbol(0x2192)])
    add_fonts(streams, [('Test', 0)])
    assert parse(monkeypatch, streams, Limits(max_records=100)).text == '→→'
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, streams, Limits(max_records=99))


def test_chpx_property_does_not_replace_ordinary_text_in_same_run(monkeypatch):
    result = parse(monkeypatch, symbol_fixture('normal ) text\r'))
    assert result.blocks == [Paragraph('normal ) text')]


@pytest.mark.parametrize('kind', ['surrogate', 'unterminated', 'odd'])
def test_bad_font_name_encoding_is_structured_error(monkeypatch, kind):
    streams = symbol_fixture(fonts=None)
    names = {'surrogate': b'\0\xd8\0\0', 'unterminated': b'A\0', 'odd': b'A'}[kind]
    raw = b'\0' + u16(400) + bytes([0, 0]) + b'\0' * 34 + names
    append_table_part(streams, 15, u16(1) + u16(0) + bytes([len(raw)]) + raw)
    with pytest.raises(InvalidDocumentError, match='font'):
        parse(monkeypatch, streams)
