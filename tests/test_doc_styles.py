"""Original synthetic MS-DOC style regressions; no external/private document text."""
from pathlib import Path
import os
import subprocess
import zipfile

import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits, parse_doc
from legacy_office_parser.models import Paragraph, Table
from test_doc import fixture, mutate, parse, sprm, u16
from test_doc_fidelity import add_chpx, add_fonts, append_table_part, symbol
from test_doc_table_properties import table_fixture


HIDE = sprm(0x083C, 1)
SHOW = sprm(0x083C, 0)


def style(index, *, kind=1, base=0xFFF, chpx=b'', papx=b'', base_size=10):
    groups = [u16(index) + papx, chpx] if kind == 1 else [chpx]
    raw = u16(0xFFE) + u16(base << 4 | kind) + u16(len(groups)) + b'\0' * (base_size - 6)
    raw += u16(1) + 'S\0'.encode('utf-16le')
    for group in groups:
        raw += u16(len(group)) + group + b'\0' * (len(group) & 1)
    return u16(len(raw)) + raw


def stylesheet(streams, records, base_size=10):
    header = u16(len(records)) + u16(base_size) + b'\0' * 14
    append_table_part(streams, 1, u16(len(header)) + header + b''.join(records))
    return streams


def pap_style(streams, index, paragraph=0):
    # Synthetic writer uses one PAPX per page; size prefix is one or two bytes.
    off = 4096 + paragraph * 512 + 64
    start = off + (1 if streams['WordDocument'][off] else 2)
    mutate(streams, 'WordDocument', start, u16(index))
    return streams


def styled_text(chpx=b'', *, text='TEXT\r', records=None, selected=1, compressed=True):
    streams = fixture([(text, compressed)], props=[b''])
    stylesheet(streams, records or [style(0, chpx=HIDE), style(1, base=0)])
    pap_style(streams, selected)
    if chpx:
        add_chpx(streams, [1024, 1024 + len(text.encode('utf-16le')) // 2 *
                          (1 if compressed else 2)], [chpx])
    return streams


@pytest.mark.parametrize('compressed', [True, False])
def test_paragraph_style_inherits_hidden(monkeypatch, compressed):
    assert parse(monkeypatch, styled_text(compressed=compressed)).blocks == [Paragraph('')]


@pytest.mark.parametrize('value,expected', [(0, 'TEXT'), (1, ''), (128, ''), (129, 'TEXT')])
def test_direct_toggle_uses_style_not_previous_direct_value(monkeypatch, value, expected):
    streams = styled_text(SHOW + sprm(0x083C, value))
    # This fixture selects fixed heading style 1; filtered text has no title.
    assert parse(monkeypatch, streams).blocks == [Paragraph(expected, 1 if expected else None)]


def test_child_explicit_false_overrides_parent(monkeypatch):
    streams = styled_text(records=[style(0, chpx=HIDE), style(1, base=0, chpx=SHOW)])
    assert parse(monkeypatch, streams).text == 'TEXT'


def test_child_toggle_relative_to_parent(monkeypatch):
    streams = styled_text(records=[style(0, chpx=HIDE),
                                  style(1, base=0, chpx=sprm(0x083C, 129))])
    assert parse(monkeypatch, streams).text == 'TEXT'


def test_character_style_chain_and_plain_reset(monkeypatch):
    records = [style(0), style(1, kind=2, chpx=HIDE), style(2, kind=2, base=1)]
    for operations, expected in [(sprm(0x4A30, u16(2)), ''),
                                 (sprm(0x4A30, u16(2)) + sprm(0x2A33, 0), 'TEXT'),
                                 (HIDE + sprm(0x4A30, u16(1)) + SHOW, 'TEXT')]:
        assert parse(monkeypatch, styled_text(operations, records=records, selected=0)).text == expected


@pytest.mark.parametrize('opcode', [0x0800, 0x0802])
def test_style_reset_preserves_deleted_and_field_hidden(monkeypatch, opcode):
    for reset in (sprm(0x2A33, 0), sprm(0x4A30, u16(10))):
        streams = fixture([('OLD\r', True)])
        add_chpx(streams, [1024, 1028], [sprm(opcode, 1) + reset])
        assert parse(monkeypatch, streams).text == ''


@pytest.mark.parametrize('opcode', [0x0800, 0x0802, 0x083C])
def test_direct_visibility_and_piece_override(monkeypatch, opcode):
    streams = fixture([('OLD', True), ('LIVE\r', True)],
                      prcs=[sprm(opcode, 0)], prms=[0, 1])
    add_chpx(streams, [1024, 1050], [sprm(opcode, 1)])
    assert parse(monkeypatch, streams).text == 'LIVE'


@pytest.mark.parametrize('prm', [0x0182, 0x0186, 0x01B8])
def test_compact_visibility(monkeypatch, prm):
    assert parse(monkeypatch, fixture([('HIDDEN\r', True)], prms=[prm])).text == ''


@pytest.mark.parametrize('value,expected', [(128, '('), (129, '→')])
def test_cfspec_relative_to_valid_style_default(monkeypatch, value, expected):
    streams = styled_text(symbol(0x2192) + sprm(0x0855, value), text='(\r',
                          records=[style(0)], selected=0)
    add_fonts(streams, [('Test', 0)])
    result = parse(monkeypatch, streams)
    assert result.text == expected
    assert not any('Style-relative CFSpec' in w for w in result.warnings)


def test_paragraph_mark_selects_style_across_piece_boundary(monkeypatch):
    streams = fixture([('TEXT', True), ('\r', False)], props=[b''])
    stylesheet(streams, [style(0), style(1, base=0, chpx=HIDE)])
    pap_style(streams, 1)
    assert parse(monkeypatch, streams).text == ''


def test_style_change_preserves_direct_table_membership_and_geometry(monkeypatch):
    from test_doc import IN, ROW, definition
    streams = table_fixture('SECRET\7VISIBLE\7\7', [
        IN + sprm(0x4600, u16(1)), IN, ROW + definition([0, 0])])
    stylesheet(streams, [style(0), style(1, base=0, chpx=HIDE)])
    result = parse(monkeypatch, streams)
    assert isinstance(result.blocks[0], Table)
    assert [[c.text for c in row] for row in result.blocks[0].rows] == [['', 'VISIBLE']]


def test_hidden_field_instruction_does_not_consume_visible_result(monkeypatch):
    streams = fixture([('\x13CODE\x14RESULT\x15\r', True)])
    add_chpx(streams, [1024, 1030, 1038], [HIDE, None])
    assert parse(monkeypatch, streams).text == 'RESULT'


def test_auxiliary_story_uses_own_paragraph_style(monkeypatch):
    streams = fixture([('BODY\rNOTE\r', True)], props=[b'', b''],
                      counts=[5, 5, 0, 0, 0, 0, 0])
    stylesheet(streams, [style(0), style(1, base=0, chpx=HIDE)])
    pap_style(streams, 1, 1)
    result = parse(monkeypatch, streams)
    assert result.text == 'BODY'
    assert result.footnotes == ''


def test_majority_resets_matching_vanish_to_paragraph_style(monkeypatch):
    majority = sprm(0xCA47, bytes([len(HIDE)]) + HIDE)
    streams = styled_text(HIDE + majority, records=[style(0)], selected=0)
    assert parse(monkeypatch, streams).text == 'TEXT'


@pytest.mark.parametrize('records,selected,message', [
    ([style(0, base=1), style(1, base=0)], 1, 'cyclic'),
    ([style(0), style(1, base=7)], 1, 'out of range'),
    ([u16(0), style(1, base=0)], 1, 'empty'),
    ([style(0, kind=2), style(1, base=0)], 1, 'kind'),
    ([style(0)], 7, 'out of range'),
])
def test_bad_style_graph(monkeypatch, records, selected, message):
    with pytest.raises(InvalidDocumentError, match=message):
        parse(monkeypatch, styled_text(records=records, selected=selected))


def test_style_depth_and_record_budget(monkeypatch):
    records = [style(0)] + [style(i, base=i-1) for i in range(1, 5)]
    streams = styled_text(records=records, selected=4)
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, streams, Limits(max_depth=3))
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, streams, Limits(max_records=98))


@pytest.mark.parametrize('papx,chpx', [(sprm(0x2416, 1), b''),
                                    (sprm(0x2417, 1), b''),
                                    (b'', sprm(0x0855, 1)), (b'', sprm(0x0800, 1))])
def test_forbidden_style_properties_do_not_invent_tables_or_hide_text(monkeypatch, papx, chpx):
    streams = styled_text(records=[style(0, papx=papx, chpx=chpx)], selected=0)
    with pytest.raises(InvalidDocumentError, match='forbidden'):
        parse(monkeypatch, streams)


@pytest.mark.parametrize('base_size', [10, 18])
def test_stdf_versions_and_empty_fixed_styles(monkeypatch, base_size):
    streams = fixture([('VISIBLE\r', True)], props=[b''])
    stylesheet(streams, [u16(0)] * 15, base_size)
    assert parse(monkeypatch, streams).text == 'VISIBLE'
    streams = fixture([('HIDDEN\r', True)], props=[b''])
    stylesheet(streams, [style(0, chpx=HIDE, base_size=base_size)], base_size)
    assert parse(monkeypatch, streams).text == ''


def test_stylesheet_truncations_are_structured_errors(monkeypatch):
    import struct
    streams = styled_text()
    offset, size = struct.unpack_from('<II', streams['WordDocument'], 154 + 8)
    data = streams['1Table'][offset:offset + size]
    for length in range(1, len(data)):
        broken = dict(streams)
        append_table_part(broken, 1, data[:length])
        with pytest.raises(InvalidDocumentError):
            parse(monkeypatch, broken)


def test_repeated_text_does_not_charge_per_character(monkeypatch):
    streams = styled_text(HIDE, text='a' * 1000 + '\r', records=[style(0)], selected=0)
    assert parse(monkeypatch, streams, Limits(max_records=115)).text == ''


def original_docx(path):
    """Minimal original fixture, generated only in pytest tmp_path for LO export."""
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    styles = f'''<w:styles xmlns:w="{ns}">
      <w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>
      <w:style w:type="paragraph" w:styleId="HiddenBase"><w:name w:val="HiddenBase"/><w:basedOn w:val="Normal"/><w:rPr><w:vanish/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="HiddenChild"><w:name w:val="HiddenChild"/><w:basedOn w:val="HiddenBase"/></w:style>
      <w:style w:type="character" w:styleId="HiddenChar"><w:name w:val="HiddenChar"/><w:rPr><w:vanish/></w:rPr></w:style>
      <w:style w:type="character" w:styleId="HiddenCharChild"><w:name w:val="HiddenCharChild"/><w:basedOn w:val="HiddenChar"/></w:style>
    </w:styles>'''
    body = f'''<w:document xmlns:w="{ns}"><w:body>
      <w:p><w:pPr><w:pStyle w:val="HiddenChild"/></w:pPr><w:r><w:t>PARA_SECRET</w:t></w:r></w:p>
      <w:p><w:r><w:t>KEEP</w:t></w:r><w:r><w:rPr><w:rStyle w:val="HiddenCharChild"/></w:rPr><w:t>CHAR_SECRET</w:t></w:r><w:r><w:t>TAIL</w:t></w:r></w:p>
      <w:p><w:pPr><w:pStyle w:val="HiddenChild"/></w:pPr><w:r><w:rPr><w:vanish w:val="0"/></w:rPr><w:t>OVERRIDE</w:t></w:r></w:p>
      <w:p><w:r><w:t>A</w:t></w:r><w:del w:id="1" w:author="Fixture" w:date="2026-01-01T00:00:00Z"><w:r><w:delText>DELETED</w:delText></w:r></w:del><w:ins w:id="2" w:author="Fixture" w:date="2026-01-01T00:00:00Z"><w:r><w:t>NEW</w:t></w:r></w:ins><w:r><w:t>Z</w:t></w:r></w:p>
      <w:sectPr/></w:body></w:document>'''
    relns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    offns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>''')
        z.writestr('_rels/.rels', f'<Relationships xmlns="{relns}"><Relationship Id="r1" Type="{offns}/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/_rels/document.xml.rels', f'<Relationships xmlns="{relns}"><Relationship Id="r1" Type="{offns}/styles" Target="styles.xml"/></Relationships>')
        z.writestr('word/document.xml', body)
        z.writestr('word/styles.xml', styles)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in original LibreOffice DOC style fixture')
def test_libreoffice_original_style_fixture(tmp_path):
    source = tmp_path / 'original-styles.docx'
    original_docx(source)
    subprocess.run(['libreoffice', '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(),
                    '--headless', '--convert-to', 'doc:MS Word 97', '--outdir', str(tmp_path),
                    str(source)], check=True, capture_output=True, timeout=45)
    result = parse_doc(tmp_path / 'original-styles.doc')
    assert [p.text for p in result.blocks if p.text] == ['KEEPTAIL', 'OVERRIDE', 'ANEWZ']


@pytest.mark.parametrize('name', ['ordinary_table', 'merged_table'])
def test_original_lo_tables_keep_geometry(name):
    import json
    root = Path(__file__).parent / 'fixtures'
    result = parse_doc(root / (name + '.doc')).to_dict()
    expected = json.loads((root / (name + '.expected.json')).read_text())
    assert [b for b in result['blocks'] if 'rows' in b] == [
        b for b in expected['blocks'] if 'rows' in b]


def test_empty_fixed_heading_style_has_default_visibility(monkeypatch):
    streams = styled_text(records=[u16(0)] * 15, selected=1)
    assert parse(monkeypatch, streams).text == 'TEXT'


def test_deleted_mark_preserves_boundary_with_explicit_diagnostic(monkeypatch):
    streams = fixture([('A\rB\r', True)])
    add_chpx(streams, [1024, 1025, 1026, 1028], [None, sprm(0x0800, 1), None])
    result = parse(monkeypatch, streams)
    assert result.blocks == [Paragraph('A'), Paragraph('B')]
    assert any('revision merging is not modeled' in w for w in result.warnings)


def test_unknown_character_style_is_not_silently_treated_as_visible(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='out of range'):
        parse(monkeypatch, styled_text(sprm(0x4A30, u16(20))))


@pytest.mark.parametrize('group', [sprm(0xC601, b'\0'), sprm(0x2602, 1)])
def test_unsupported_paragraph_style_reselection_is_explicit(monkeypatch, group):
    from legacy_office_parser.errors import UnsupportedFormatError
    with pytest.raises(UnsupportedFormatError, match='style'):
        parse(monkeypatch, fixture([('TEXT\r', True)], props=[group]))


def test_unsupported_compact_style_increment_is_explicit(monkeypatch):
    from legacy_office_parser.errors import UnsupportedFormatError
    with pytest.raises(UnsupportedFormatError, match='style'):
        parse(monkeypatch, fixture([('TEXT\r', True)], prms=[0x0108]))


def test_unsupported_character_style_permutation_is_explicit(monkeypatch):
    from legacy_office_parser.errors import UnsupportedFormatError
    with pytest.raises(UnsupportedFormatError, match='style'):
        parse(monkeypatch, styled_text(sprm(0xCA31, b'\0')))


@pytest.mark.parametrize('opcode', [0x083C, 0x0800, 0x0802])
def test_invalid_visibility_toggle_is_structured_error(monkeypatch, opcode):
    with pytest.raises(InvalidDocumentError, match='toggle'):
        parse(monkeypatch, styled_text(sprm(opcode, 2)))
