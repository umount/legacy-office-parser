"""ODT note regressions using only original synthetic in-memory packages."""
from pathlib import Path
import json
import os
import signal
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from legacy_office_parser.models import Paragraph
from legacy_office_parser.odf import parse_odf_bytes

import pytest

from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from test_odf import parse


def note(body, kind='footnote', citation='1'):
    return (f'<text:note text:note-class="{kind}" text:id="note1">'
            f'<text:note-citation>{citation}</text:note-citation>'
            f'<text:note-body>{body}</text:note-body></text:note>')


def test_footnotes_endnotes_are_separate_and_not_duplicated():
    doc = parse('<text:p>Before' + note('<text:p>Foot one</text:p>', citation='77') +
                ' middle' + note('<text:p>End one</text:p>', 'endnote', 'ix') +
                ' after</text:p><text:p>Next' + note('<text:p>Foot two</text:p>', citation='*') +
                note('<text:p>End two</text:p>', 'endnote') + '</text:p>')
    assert [b.text for b in doc.blocks] == ['Before middle after', 'Next']
    assert doc.footnotes == 'Foot one\n\nFoot two'
    assert doc.endnotes == 'End one\n\nEnd two'
    assert doc.text == 'Before middle after\n\nNext\n\nFoot one\n\nFoot two\n\nEnd one\n\nEnd two'
    assert doc.to_dict()['footnotes'] == doc.footnotes
    assert doc.warnings == []


def test_note_inline_formatting_whitespace_lists_and_tables():
    body = ('<text:p> Alpha <text:span> beta</text:span><text:s text:c="2"/>X'
            '<text:tab/>Y<text:line-break/>Z <text:a>link</text:a></text:p>'
            '<text:list><text:list-item><text:p>item</text:p></text:list-item></text:list>'
            '<table:table><table:table-row><table:table-cell><text:p>A</text:p>'
            '<text:p>B</text:p></table:table-cell><table:table-cell><text:p>C</text:p>'
            '</table:table-cell></table:table-row></table:table><text:p>last</text:p>')
    doc = parse('<text:h>Title<text:span>' + note(body) + '</text:span> tail</text:h>')
    assert doc.blocks[0].text == 'Title tail'
    assert doc.footnotes == 'Alpha beta  X\tY\nZ link\n\nitem\n\nA\nB\tC\n\nlast'
    assert len(doc.blocks) == 1
    assert doc.warnings == []


def test_notes_in_sections_lists_and_table_cells():
    doc = parse('<text:section><text:list><text:list-item><text:p>List' +
                note('<text:p>List note</text:p>') + '</text:p></text:list-item></text:list>'
                '<table:table><table:table-row><table:table-cell><text:p>Cell' +
                note('<text:p>Cell note</text:p>', 'endnote') +
                '</text:p></table:table-cell></table:table-row></table:table></text:section>')
    assert doc.footnotes == 'List note'
    assert doc.endnotes == 'Cell note'
    assert doc.blocks[1].rows[0][0].text == 'Cell'
    assert doc.warnings == []


@pytest.mark.parametrize('wrapper', [
    '<office:annotation>{}</office:annotation>',
    '<text:tracked-changes><text:deletion>{}</text:deletion></text:tracked-changes>',
    '<text:variable-set text:display="none">{}</text:variable-set>',
    '<text:hidden-text text:is-hidden="true">{}</text:hidden-text>',
])
def test_notes_in_omitted_content_are_not_scraped(wrapper):
    doc = parse('<text:p>A' + wrapper.format(note('<text:p>OMITTED</text:p>')) + 'B</text:p>')
    assert doc.text == 'AB'
    assert doc.footnotes == doc.endnotes == ''


def test_omitted_content_inside_note_and_nested_note():
    body = ('<text:p>A<office:annotation><text:p>OMITTED</text:p></office:annotation>' +
            note('<text:p>NESTED</text:p>', 'endnote') + 'B</text:p>')
    doc = parse('<text:p>Main' + note(body) + '</text:p>')
    assert doc.footnotes == 'AB'
    assert doc.endnotes == ''
    assert doc.text == 'Main\n\nAB'
    assert doc.warnings


@pytest.mark.parametrize('xml', [
    '<text:note><text:note-body><text:p>omitted</text:p></text:note-body></text:note>',
    note('<text:p>omitted</text:p>', 'unknown'),
    '<text:note text:note-class="footnote"><text:note-citation>1</text:note-citation></text:note>',
    '<text:note text:note-class="footnote"><text:note-body/><text:note-body/></text:note>',
])
def test_malformed_notes_warn_without_leaking_text(xml):
    doc = parse('<text:p>A' + xml + 'B</text:p>')
    assert doc.text == 'AB'
    assert doc.footnotes == doc.endnotes == ''
    assert any('note omitted' in w for w in doc.warnings)


def test_empty_notes_do_not_add_separators():
    doc = parse('<text:p>A' + note('<text:p/>') +
                note('<text:p>body</text:p>') + note('') + 'B</text:p>')
    assert doc.text == 'AB\n\nbody'
    assert doc.warnings == []


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
def test_note_separators_are_bounded(kind):
    expanded = '<text:p><text:s text:c="600"/></text:p>'
    xml = '<text:p>' + note(expanded, kind) * 2 + '</text:p>'
    with pytest.raises(LimitExceededError):
        parse(xml, limits=Limits(max_text_chars=1201))
    assert len(parse(xml, limits=Limits(max_text_chars=1202)).text) == 1202


def test_main_text_and_note_separator_are_bounded():
    xml = '<text:p>A' + note('<text:p><text:s text:c="1200"/></text:p>') + '</text:p>'
    with pytest.raises(LimitExceededError, match='rendered text'):
        parse(xml, limits=Limits(max_text_chars=1202))
    assert len(parse(xml, limits=Limits(max_text_chars=1203)).text) == 1203


def test_note_table_uses_cell_limits():
    xml = '<text:p>' + note('<table:table><table:table-row>'
                           '<table:table-cell table:number-columns-repeated="3"/>'
                           '</table:table-row></table:table>') + '</text:p>'
    with pytest.raises(LimitExceededError, match='cell limit'):
        parse(xml, limits=Limits(max_cells=2))


# These fixtures and expectations are authored independently of the parser.
# Saved LibreOffice XML is a second oracle; no conversion is required for unit tests.

FIXTURES = Path(__file__).parent / 'fixtures' / 'odf_notes'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def docx_text_parts(parts):
    """Compare text runs only for these fixtures (no authored tabs/breaks).

    This excludes footnoteRef/endnoteRef, reference anchors and LO's leading
    citation tab. Separator pseudo-notes are excluded by type, not numeric ID.
    No digit stripping or whitespace normalization can hide a text difference.
    """
    result = {}
    for kind in ('main', 'footnotes', 'endnotes'):
        root = ET.fromstring(parts[kind])
        def paragraphs(element):
            return [''.join(t.text or '' for t in p.iter(W + 't'))
                    for p in element.iter(W + 'p')]
        if kind == 'main':
            result[kind] = [p for p in paragraphs(root) if p]
        else:
            result[kind] = [paragraphs(n) for n in root
                            if n.get(W + 'type', 'normal') == 'normal']
    return result


def fixture_model(name):
    return parse_odf_bytes((FIXTURES / f'{name}.odt').read_bytes(), Limits())


def main_paragraphs(doc):
    return [text for block in doc.blocks for text in (
        [block.text] if isinstance(block, Paragraph)
        else [p for row in block.rows for cell in row for p in cell.text.split('\n')]) if text]


@pytest.mark.parametrize('name', ['ordinary', 'repeated'])
def test_public_fixture_matches_independent_expectations(name):
    expected = json.loads((FIXTURES / f'{name}.expected.json').read_text())
    doc = fixture_model(name)
    assert main_paragraphs(doc) == expected['main']
    for kind in ('footnotes', 'endnotes'):
        assert getattr(doc, kind) == '\n\n'.join(p for n in expected[kind] for p in n)
    assert doc.warnings == []
    with ZipFile(FIXTURES / f'{name}.odt') as package:
        assert package.read('content.xml') == (FIXTURES / f'{name}.content.xml').read_bytes()


@pytest.mark.parametrize('name', ['ordinary', 'repeated'])
def test_recorded_libreoffice_docx_xml(name):
    parts = {kind: (FIXTURES / f'{name}.lo' / f'{part}.xml').read_bytes()
             for kind, part in [('main', 'document'), ('footnotes', 'footnotes'),
                                ('endnotes', 'endnotes')]}
    actual = docx_text_parts(parts)
    expected = json.loads((FIXTURES / f'{name}.expected.json').read_text())
    if name == 'ordinary':
        assert actual == expected
    else:
        # LO 7.4.7.2 imports the repeated columns but only the first repeated row.
        assert actual == {'main': ['Повторы.', 'А', 'А', 'Б'],
                          'footnotes': [['Повтор А.'], ['Повтор А.']],
                          'endnotes': [['Повтор Б.']]}
        assert expected['main'] == actual['main'] + actual['main'][1:]
        assert expected['footnotes'] == actual['footnotes'] * 2
        assert expected['endnotes'] == actual['endnotes'] * 2


def test_repeated_notes_follow_row_major_order():
    a = note('<text:p>A1</text:p>') + note('<text:p>A2</text:p>')
    b = note('<text:p>B</text:p>')
    xml = ('<table:table><table:table-row table:number-rows-repeated="2">'
           '<table:table-cell table:number-columns-repeated="2"><text:p>' + a +
           '</text:p></table:table-cell><table:table-cell><text:p>' + b +
           '</text:p></table:table-cell></table:table-row></table:table>')
    doc = parse(xml)
    assert doc.footnotes.split('\n\n') == ['A1', 'A2', 'A1', 'A2', 'B'] * 2


@pytest.mark.parametrize('attribute', ['table:number-columns-repeated="2"',
                                       'table:number-rows-repeated="2"'])
def test_repeated_note_text_is_charged(attribute):
    row_attr = attribute if 'rows' in attribute else ''
    cell_attr = attribute if 'columns' in attribute else ''
    xml = (f'<table:table><table:table-row {row_attr}><table:table-cell {cell_attr}>'
           '<text:p>' + note('<text:p><text:s text:c="1000"/></text:p>') +
           '</text:p></table:table-cell></table:table-row></table:table>')
    with pytest.raises(LimitExceededError, match='expanded text'):
        parse(xml, limits=Limits(max_text_chars=2001))
    with pytest.raises(LimitExceededError, match='rendered text'):
        parse(xml, limits=Limits(max_text_chars=2004))
    assert len(parse(xml, limits=Limits(max_text_chars=2005)).footnotes) == 2002


def test_repeated_note_tables_are_charged_to_cell_budget():
    inner = '<table:table><table:table-row><table:table-cell/></table:table-row></table:table>'
    xml = ('<table:table><table:table-row table:number-rows-repeated="2">'
           '<table:table-cell table:number-columns-repeated="2"><text:p>' + note(inner) +
           '</text:p></table:table-cell></table:table-row></table:table>')
    with pytest.raises(LimitExceededError, match='cell limit'):
        parse(xml, limits=Limits(max_cells=7))
    assert len(parse(xml, limits=Limits(max_cells=8)).blocks[0].rows) == 2


@pytest.mark.skipif(os.environ.get('ODF_NOTES_LIBREOFFICE') != '1',
                    reason='opt-in real LibreOffice conversion')
def test_live_libreoffice_ordinary_notes(tmp_path):
    # tmp_path is unique per run; timeout kills the complete conversion process group.
    profile = tmp_path / 'profile'
    command = ['libreoffice', f'-env:UserInstallation={profile.as_uri()}', '--headless',
               '--convert-to', 'docx:Office Open XML Text', '--outdir', str(tmp_path),
               str(FIXTURES / 'ordinary.odt')]
    env = dict(os.environ, GSETTINGS_BACKEND='memory', SAL_USE_VCLPLUGIN='svp',
               XDG_RUNTIME_DIR=str(tmp_path))
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=env, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        assert process.returncode == 0, stdout + stderr
    with ZipFile(tmp_path / 'ordinary.docx') as package:
        parts = {kind: package.read(f'word/{part}.xml') for kind, part in
                 [('main', 'document'), ('footnotes', 'footnotes'), ('endnotes', 'endnotes')]}
    expected = json.loads((FIXTURES / 'ordinary.expected.json').read_text())
    assert docx_text_parts(parts) == expected
