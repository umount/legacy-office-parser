"""Auxiliary RTF tables preserve relationships without duplicating text output."""
from pathlib import Path

import pytest

from legacy_office_parser import parse_rtf, Limits
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.models import Cell, Note, NoteBodyRange, Paragraph, Table
from test_rtf_nested import nested, outer

TABLE = r'\trowd\cellx100\cellx200 A\cell B\cell\row'


def parse(body, **limits):
    return parse_rtf(('{\\rtf1 ' + body + '}').encode(), limits=Limits(**limits))


@pytest.mark.parametrize('destination,story', [
    ('header', 'headers_footers'), ('footer', 'headers_footers'),
    ('footnote', 'footnotes'), (r'footnote\ftnalt', 'endnotes'),
    ('shptxt', 'textboxes'),
])
def test_story_table_structure_and_legacy_projection(destination, story):
    doc = parse('Body{\\' + destination + ' ' + TABLE + '}Tail')
    assert doc.blocks == [Paragraph('BodyTail')]
    assert doc.story_blocks == {story: [Table([[Cell('A'), Cell('B')]])]}
    assert getattr(doc, story) == 'A\tB'
    assert doc.text == 'BodyTail\n\nA\tB'
    assert 'flattened' not in '\n'.join(doc.warnings)
    assert doc.to_dict()['story_blocks'][story][0]['rows'][0][1]['text'] == 'B'


def test_all_sinks_of_same_story_keep_source_order():
    doc = parse(r'{\header Before}{\footer ' + TABLE + r'}{\header After}')
    assert doc.story_blocks['headers_footers'] == [
        Paragraph('Before'), Table([[Cell('A'), Cell('B')]]), Paragraph('After')]
    assert doc.headers_footers == 'Before\nA\tB\nAfter'
    assert doc.text == doc.headers_footers


def test_pure_text_notes_retain_ranges_while_non_note_stories_keep_legacy_json():
    non_notes = r'{\header H}{\shptxt T}'
    plain = parse(non_notes)
    assert not plain.story_blocks
    assert 'story_blocks' not in plain.to_dict()
    assert not plain.notes

    doc = parse(non_notes + r'{\footnote N}')
    assert doc.story_blocks == {'footnotes': [Paragraph('N')]}
    assert doc.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert doc.headers_footers == 'H' and doc.textboxes == 'T'
    assert doc.footnotes == 'N'
    assert doc.text == 'N\n\nH\n\nT'
    result = doc.to_dict()
    assert result['story_blocks'] == {'footnotes': [{'text': 'N', 'kind': 'paragraph'}]}
    assert result['notes'] == [{
        'kind': 'footnote', 'ordinal': 1,
        'body': {'story': 'footnotes', 'block_start': 0, 'block_end': 1},
        'source_cp': None, 'anchor_path': None,
        'reference_kind': 'unknown', 'visibility': ['unknown'],
    }]


def test_nested_structure_survives_auxiliary_projection():
    doc = parse(r'{\header ' + outer(nested('Nested')) + '}')
    cell = doc.story_blocks['headers_footers'][0].rows[0][0]
    assert cell.text == 'Nested'
    assert cell.blocks == [Table([[Cell('Nested')]])]
    assert doc.headers_footers == 'Nested' and doc.text == 'Nested'


def test_horizontal_merge_and_empty_cells_keep_positions():
    doc = parse(r'{\footnote\trowd\clmgf\cellx100\clmrg\cellx200\cellx300 '
                r'Anchor\cell\cell\cell\row}')
    assert doc.story_blocks['footnotes'] == [Table([[
        Cell('Anchor', col_span=2), Cell(covered=True), Cell()]])]
    assert doc.footnotes == 'Anchor\t\t'


def test_empty_table_remains_structured():
    doc = parse(r'{\header\trowd\cellx100\cell\row}')
    assert doc.story_blocks == {'headers_footers': [Table([[Cell()]])]}
    assert doc.headers_footers == ''


def test_both_blocks_and_aggregate_are_budgeted():
    body = r'{\header ' + TABLE + '}'
    assert parse(body, max_text_chars=6).headers_footers == 'A\tB'
    with pytest.raises(LimitExceededError):
        parse(body, max_text_chars=5)
    with pytest.raises(LimitExceededError):
        parse(body, max_cells=1)


def test_repeated_stories_are_not_deduplicated():
    doc = parse(r'{\header ' + TABLE + r'}{\footer ' + TABLE + '}')
    a, b = doc.story_blocks['headers_footers']
    assert a == b and a is not b
    assert doc.headers_footers == 'A\tB\nA\tB'


def test_original_fixture():
    doc = parse_rtf(Path(__file__).parent / 'fixtures/rtf_stories/auxiliary_tables.rtf')
    assert doc.blocks == [Paragraph('Body')]
    assert doc.headers_footers == 'Before\nA\tB\nAfter'
    assert doc.footnotes == 'C\tD'
    assert doc.story_blocks == {
        'headers_footers': [Paragraph('Before'), Table([[Cell('A'), Cell('B')]]),
                            Paragraph('After')],
        'footnotes': [Table([[Cell('C'), Cell('D')]])],
    }


def test_original_fixture_libreoffice_tables(tmp_path):
    import os
    import subprocess
    import sys
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    if os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1':
        pytest.skip('opt-in LibreOffice auxiliary-table oracle')
    root = Path(__file__).resolve().parents[1]
    source = root / 'tests/fixtures/rtf_stories/auxiliary_tables.rtf'
    result = subprocess.run([sys.executable, str(root / 'tools/check_performance.py'),
        '--convert-child', '/usr/bin/libreoffice', str(source), str(tmp_path), 'docx'],
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(tmp_path / 'auxiliary_tables.docx') as archive:
        notes = ET.fromstring(archive.read('word/footnotes.xml'))
        headers = _active_headers(archive)
    def tables(elements):
        return [[[''.join(c.itertext()) for c in row.findall('w:tc', ns)]
                 for row in table.findall('w:tr', ns)]
                for element in elements for table in element.findall('.//w:tbl', ns)]
    # This source header applies to every page. LibreOffice versions may emit
    # separate identical first/default/even parts; check each whole variant.
    assert headers
    actual_headers = [tables([header]) for header in headers]
    assert all(value == [[['A', 'B']]] for value in actual_headers), actual_headers
    assert tables([notes]) == [[['C', 'D']]]
    doc = parse_rtf(source)
    for key, expected in [('headers_footers', [['A', 'B']]), ('footnotes', [['C', 'D']])]:
        table, = [b for b in doc.story_blocks[key] if isinstance(b, Table)]
        assert [[c.text for c in row] for row in table.rows] == expected


def _active_headers(archive):
    """Resolve the authored single section, excluding inactive template parts."""
    import posixpath
    import xml.etree.ElementTree as ET
    w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    rel = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    document = ET.fromstring(archive.read('word/document.xml'))
    settings = ET.fromstring(archive.read('word/settings.xml'))
    section, = document.findall('.//' + w + 'sectPr')
    def enabled(element):
        return element is not None and element.get(w + 'val', 'true') not in ('0', 'false', 'off')
    active = {'default'}
    if enabled(section.find(w + 'titlePg')):
        active.add('first')
    if enabled(settings.find(w + 'evenAndOddHeaders')):
        active.add('even')
    relationships = {r.get('Id'): r for r in
        ET.fromstring(archive.read('word/_rels/document.xml.rels'))}
    headers = []
    for reference in section.findall(w + 'headerReference'):
        if reference.get(w + 'type') not in active:
            continue
        target = relationships[reference.get(rel + 'id')]
        assert target.get('TargetMode', 'Internal') == 'Internal'
        assert target.get('Type').endswith('/header')
        name = posixpath.normpath(posixpath.join('word', target.get('Target')))
        headers.append(ET.fromstring(archive.read(name)))
    return headers


@pytest.mark.parametrize('title_enabled,expected', [('0', ['A']), ('1', ['A', ''])])
def test_reference_oracle_ignores_only_inactive_first_header(title_enabled, expected):
    from io import BytesIO
    from zipfile import ZipFile
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    r = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with ZipFile(BytesIO(), 'w') as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="{w}" xmlns:r="{r}">'
            '<w:body><w:sectPr><w:headerReference w:type="default" r:id="a"/>'
            '<w:headerReference w:type="first" r:id="b"/>'
            f'<w:titlePg w:val="{title_enabled}"/></w:sectPr></w:body></w:document>')
        archive.writestr('word/settings.xml', f'<w:settings xmlns:w="{w}"/>')
        archive.writestr('word/_rels/document.xml.rels', '<Relationships>'
            f'<Relationship Id="a" Type="{r}/header" Target="header1.xml"/>'
            f'<Relationship Id="b" Type="{r}/header" Target="header2.xml"/></Relationships>')
        archive.writestr('word/header1.xml', f'<w:hdr xmlns:w="{w}"><w:p><w:r><w:t>A</w:t></w:r></w:p></w:hdr>')
        archive.writestr('word/header2.xml', f'<w:hdr xmlns:w="{w}"><w:p/></w:hdr>')
        assert [''.join(header.itertext()) for header in _active_headers(archive)] == expected
