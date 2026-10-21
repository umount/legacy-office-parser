"""Original synthetic ODT stories, independent expectations and LibreOffice oracle."""
import json
import os
from pathlib import Path
import signal
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph
from legacy_office_parser.odf import parse_odf_bytes
from test_odf import NS, parse

FIXTURES = Path(__file__).parent / 'fixtures' / 'odf_stories'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'


def frame(body):
    return '<draw:frame><draw:text-box>' + body + '</draw:text-box></draw:frame>'


def note(body, kind='footnote'):
    return (f'<text:note text:note-class="{kind}"><text:note-citation>7</text:note-citation>'
            '<text:note-body>' + body + '</text:note-body></text:note>')


def table(body, rows=1, columns=1):
    return (f'<table:table><table:table-row table:number-rows-repeated="{rows}">'
            f'<table:table-cell table:number-columns-repeated="{columns}">' + body +
            '</table:table-cell></table:table-row></table:table>')


def styles(masters, common='', automatic=''):
    namespaces = ' '.join(f'xmlns:{k}="{v}"' for k, v in NS.items())
    namespaces += ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    return (f'<office:document-styles {namespaces}><office:styles>{common}</office:styles>'
            f'<office:automatic-styles>{automatic}</office:automatic-styles><office:master-styles>' + masters +
            '</office:master-styles></office:document-styles>')


def master(body, name='Standard'):
    return f'<style:master-page style:name="{name}">' + body + '</style:master-page>'


def test_inline_block_group_and_cell_frames_are_separate():
    doc = parse('<text:p>A<text:span>' + frame('<text:p>inline</text:p>') +
                '</text:span>B</text:p><draw:g><draw:a>' + frame('<text:p>block</text:p>') +
                '</draw:a></draw:g>' + table('<text:p>C' + frame('<text:p>cell inline</text:p>') +
                                           'D</text:p>' + frame('<text:p>cell block</text:p>')))
    assert doc.blocks[0].text == 'AB'
    assert len(doc.blocks) == 2
    assert doc.blocks[1].rows[0][0].text == 'CD'
    assert doc.textboxes == 'inline\n\nblock\n\ncell inline\n\ncell block'
    assert doc.text == 'AB\n\nCD\n\n' + doc.textboxes
    assert any('anchor' in w for w in doc.warnings)


def test_nested_frames_in_encounter_order_and_empty_frames():
    doc = parse(frame('<text:p>Outer ' + frame('<text:p>Inner</text:p>') + ' end</text:p>') +
                frame('') + frame(frame('<text:p>Third</text:p>')))
    assert doc.textboxes == 'Outer end\n\nInner\n\nThird'
    assert doc.blocks == []
    assert doc.text == doc.textboxes


def test_frame_lists_tables_whitespace_and_notes():
    body = ('<text:p>Ёж<text:s text:c="2"/>чай<text:tab/>X<text:line-break/>Y' +
            note('<text:p>Foot</text:p>') + 'Z</text:p>'
            '<text:list><text:list-item><text:p>Item</text:p></text:list-item></text:list>' +
            table('<text:p>Cell' + note('<text:p>End</text:p>', 'endnote') + '</text:p>'))
    doc = parse('<text:p>Main' + frame(body) + '</text:p>')
    assert doc.blocks[0].text == 'Main'
    assert doc.textboxes == 'Ёж  чай\tX\nYZ\n\nItem\n\nCell'
    assert doc.footnotes == 'Foot'
    assert doc.endnotes == 'End'
    assert doc.text.count('Foot') == doc.text.count('End') == 1


def test_frames_inside_notes_do_not_bypass_nested_note_guard():
    doc = parse('<text:p>Main' + note('<text:p>Note' +
                frame('<text:p>Frame' + note('<text:p>OMITTED</text:p>') + ' tail</text:p>') +
                '</text:p>') + '</text:p>')
    assert doc.footnotes == 'Note'
    assert doc.textboxes == 'Frame tail'
    assert 'OMITTED' not in doc.text
    assert any('note omitted' in w for w in doc.warnings)


@pytest.mark.parametrize('wrapper', [
    '<office:annotation>{}</office:annotation>',
    '<text:tracked-changes>{}</text:tracked-changes>',
    '<text:variable-set text:display="none">{}</text:variable-set>',
    '<text:hidden-text text:is-hidden="true">{}</text:hidden-text>',
    '<draw:object>{}</draw:object>',
    '<draw:image>{}</draw:image>',
])
def test_omitted_subtrees_do_not_leak_frames_or_notes(wrapper):
    secret = frame('<text:p>OMITTED' + note('<text:p>OMITTED NOTE</text:p>') + '</text:p>')
    doc = parse('<text:p>A' + wrapper.format(secret) + 'B</text:p>')
    assert doc.text == 'AB'
    assert doc.textboxes == doc.footnotes == ''


def test_frame_replacements_and_metadata_are_not_scraped():
    doc = parse('<draw:frame><draw:text-box><text:p>Visible</text:p></draw:text-box>'
                '<draw:image><text:p>IMAGE</text:p></draw:image>'
                '<draw:object><text:p>OBJECT</text:p></draw:object>'
                '<draw:description><text:p>DESCRIPTION</text:p></draw:description></draw:frame>')
    assert doc.text == 'Visible'


def test_master_variants_pool_once_but_unused_master_stories_are_absent():
    variants = ''.join(f'<style:{tag}><text:p>{tag}</text:p></style:{tag}>' for tag in
                       ('header', 'header-left', 'header-first', 'footer', 'footer-left', 'footer-first'))
    disabled = '<style:header-left style:display="false"><text:p>OMITTED</text:p></style:header-left>'
    unused = '<style:header><text:p>unusedmaster_header' + frame(
        '<text:p>unusedmaster_box</text:p>') + note('<text:p>unusedmaster_note</text:p>') + '</text:p></style:header>'
    xml = styles(master(variants + disabled) + master(unused, 'Unused'))
    doc = parse('<text:p>First<text:soft-page-break/>Second</text:p>', extra={'styles.xml': xml})
    assert doc.headers_footers == 'header\n\nheader-left\n\nheader-first\n\nfooter\n\nfooter-left\n\nfooter-first'
    assert doc.blocks[0].text == 'FirstSecond'
    assert any('variant identities' in w for w in doc.warnings)
    assert any('disabled' in w for w in doc.warnings)
    assert 'unusedmaster' not in doc.text
    assert doc.textboxes == doc.footnotes == ''


def test_header_tables_frames_and_notes_remain_separate():
    header = '<style:header>' + table('<text:p>Header' + frame('<text:p>Box</text:p>') +
                                     note('<text:p>Foot</text:p>') + '</text:p>') + '</style:header>'
    doc = parse('<text:p>Main</text:p>', extra={'styles.xml': styles(master(header))})
    assert doc.headers_footers == 'Header'
    assert doc.textboxes == 'Box'
    assert doc.footnotes == 'Foot'
    assert doc.text == 'Main\n\nFoot\n\nHeader\n\nBox'


def test_master_scan_does_not_scrape_arbitrary_descendants():
    hidden = master('<style:header><text:p>OMITTED</text:p></style:header>')
    xml = styles('<office:annotation>' + hidden + '</office:annotation>')
    doc = parse('<text:p>Main</text:p>', extra={'styles.xml': xml})
    assert doc.text == 'Main'


def test_repeated_frames_with_notes_keep_reading_order():
    body = '<text:p>C' + frame('<text:p>A' + note('<text:p>N1</text:p>') + '</text:p>')
    # Build two frames per cell to detect cell-major versus story-major cloning.
    body += frame('<text:p>B' + note('<text:p>N2</text:p>', 'endnote') + '</text:p>') + '</text:p>'
    doc = parse(table(body, rows=2, columns=2))
    assert doc.textboxes.split('\n\n') == ['A', 'B'] * 4
    assert doc.footnotes.split('\n\n') == ['N1'] * 4
    assert doc.endnotes.split('\n\n') == ['N2'] * 4
    assert [[c.text for c in r] for r in doc.blocks[0].rows] == [['C', 'C'], ['C', 'C']]


def test_repeated_frame_tables_charge_cells():
    xml = table(frame(table('<text:p>X</text:p>')), rows=2, columns=2)
    with pytest.raises(LimitExceededError, match='cell limit'):
        parse(xml, limits=Limits(max_cells=7))
    assert parse(xml, limits=Limits(max_cells=8)).textboxes == 'X\n\nX\n\nX\n\nX'


@pytest.mark.parametrize('location', ['frame', 'header'])
def test_story_text_separators_and_main_are_bounded(location):
    text = '<text:p><text:s text:c="1000"/></text:p>' * 2
    extra = {'styles.xml': styles(master('<style:header>' + text + '</style:header>'))} if location == 'header' else {}
    body = '<text:p>M</text:p>' + (frame(text) if location == 'frame' else '')
    with pytest.raises(LimitExceededError, match='expanded text'):
        parse(body, extra=extra, limits=Limits(max_text_chars=2001))
    with pytest.raises(LimitExceededError, match='rendered text'):
        parse(body, extra=extra, limits=Limits(max_text_chars=2004))
    assert len(parse(body, extra=extra, limits=Limits(max_text_chars=2005)).text) == 2005


def test_frames_and_notes_share_text_budget():
    xml = frame('<text:p><text:s text:c="1000"/>' +
                note('<text:p><text:s text:c="1000"/></text:p>') + '</text:p>')
    with pytest.raises(LimitExceededError, match='expanded text'):
        parse(xml, limits=Limits(max_text_chars=1999))
    assert len(parse(xml, limits=Limits(max_text_chars=2002)).text) == 2002


def test_repeated_frame_text_is_charged():
    xml = table(frame('<text:p><text:s text:c="1000"/></text:p>'), rows=2, columns=2)
    with pytest.raises(LimitExceededError, match='expanded text'):
        parse(xml, limits=Limits(max_text_chars=4005))
    assert len(parse(xml, limits=Limits(max_text_chars=4011)).textboxes) == 4006


@pytest.mark.parametrize('location', ['frame', 'header'])
def test_story_recursion_is_bounded_by_xml_depth(location):
    body = '<text:p>Deep</text:p>'
    for _ in range(12):
        body = frame(body)
    extra = {'styles.xml': styles(master('<style:header>' + body + '</style:header>'))} if location == 'header' else {}
    with pytest.raises(LimitExceededError, match='depth'):
        parse(body if location == 'frame' else '', extra=extra, limits=Limits(max_depth=16))


def test_deep_allowed_frames_do_not_raise_python_recursion_error():
    body = 'Deep'
    for _ in range(80):
        body = frame('<text:p>' + body + '</text:p>')
    assert parse(body, limits=Limits(max_depth=256)).textboxes == 'Deep'


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_other_odf_formats_keep_existing_frame_routing(fmt):
    body = frame('<text:p>Existing</text:p>')
    body = table(body) if fmt == 'ods' else '<draw:page>' + body + '</draw:page>'
    doc = parse(body, fmt)
    assert 'Existing' in doc.text
    assert doc.textboxes == doc.headers_footers == ''


def docx_stories(data):
    """Oracle for this fixture: select one AlternateContent branch; split text boxes.

    Only w:t is needed here: the authored fixture has no tabs/breaks/fields.
    Parent paragraph text excludes nested txbxContent rather than using itertext.
    """
    result = {'main': [], 'textboxes': []}

    def children(element):
        if element.tag == MC + 'AlternateContent':
            branch = element.find(MC + 'Choice')
            if branch is None:
                branch = element.find(MC + 'Fallback')
            return [] if branch is None else list(branch)
        return list(element)

    def walk(element, destination):
        if element.tag == W + 'txbxContent':
            destination = 'textboxes'
        if element.tag == W + 'p':
            tokens = []

            def inline(node):
                if node.tag == W + 'txbxContent':
                    walk(node, 'textboxes')
                elif node.tag == W + 't':
                    tokens.append(node.text or '')
                else:
                    for child in children(node):
                        inline(child)
            inline(element)
            value = ''.join(tokens)
            if value:
                result[destination].append(value)
            return
        for child in children(element):
            walk(child, destination)

    walk(ET.fromstring(data), 'main')
    return result


def comparison_parts(parts):
    result = docx_stories(parts['document'])
    result['headers_footers'] = []
    for name in ('header1', 'footer1'):
        story = docx_stories(parts[name])
        result['headers_footers'].extend(story['main'])
        result['textboxes'].extend(story['textboxes'])
    return result


def test_public_fixture_matches_independent_expectations():
    expected = json.loads((FIXTURES / 'expected.json').read_text())
    doc = parse_odf_bytes((FIXTURES / 'stories.odt').read_bytes(), Limits())
    main = [p for b in doc.blocks for p in (
        [b.text] if isinstance(b, Paragraph) else [c.text for row in b.rows for c in row])]
    assert main == expected['main']
    assert doc.textboxes == '\n\n'.join(expected['textboxes'])
    assert doc.headers_footers == '\n\n'.join(expected['headers_footers'])
    assert doc.footnotes == doc.endnotes == ''
    assert 'unusedmaster' not in doc.text
    for value in expected['textboxes'] + expected['headers_footers']:
        assert doc.text.count(value) == 1
    with ZipFile(FIXTURES / 'stories.odt') as archive:
        for name in ('content.xml', 'styles.xml'):
            assert archive.read(name) == (FIXTURES / name).read_bytes()
        assert archive.read('META-INF/manifest.xml') == (FIXTURES / 'manifest.xml').read_bytes()


def test_recorded_libreoffice_stories_match_independent_expectations():
    expected = json.loads((FIXTURES / 'expected.json').read_text())
    parts = {name: (FIXTURES / 'lo' / (name + '.xml')).read_bytes()
             for name in ('document', 'header1', 'footer1')}
    # The saved DOCX has two physical textboxes per frame (Choice + Fallback).
    assert len(list(ET.fromstring(parts['document']).iter(W + 'txbxContent'))) == 4
    assert all(b'unusedmaster' not in data for data in parts.values())
    assert comparison_parts(parts) == expected


def convert_with_libreoffice(work):
    command = ['libreoffice', f'-env:UserInstallation={(work / "profile").as_uri()}',
               '--headless', '--convert-to', 'docx:Office Open XML Text',
               '--outdir', str(work), str(FIXTURES / 'stories.odt')]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True,
                          env=dict(os.environ, GSETTINGS_BACKEND='memory',
                                   SAL_USE_VCLPLUGIN='svp', XDG_RUNTIME_DIR=str(work))) as process:
        try:
            stdout, stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        assert process.returncode == 0, stdout + stderr
    with ZipFile(work / 'stories.docx') as archive:
        for name in archive.namelist():
            if name.startswith(('word/document', 'word/header', 'word/footer')) and name.endswith('.xml'):
                assert b'unusedmaster' not in archive.read(name)
        return {name: archive.read(f'word/{name}.xml')
                for name in ('document', 'header1', 'footer1')}


@pytest.mark.skipif(os.environ.get('ODF_STORIES_LIBREOFFICE') != '1',
                    reason='opt-in real LibreOffice conversion')
def test_live_libreoffice_stories(tmp_path):
    assert comparison_parts(convert_with_libreoffice(tmp_path)) == json.loads(
        (FIXTURES / 'expected.json').read_text())


def test_covered_cell_frame_is_not_extracted():
    xml = ('<table:table><table:table-row><table:covered-table-cell>' +
           frame('<text:p>OMITTED' + note('<text:p>OMITTED NOTE</text:p>') + '</text:p>') +
           '</table:covered-table-cell></table:table-row></table:table>')
    doc = parse(xml)
    assert doc.textboxes == doc.footnotes == doc.text == ''


def test_equal_frames_are_distinct_stories_not_deduplicated_by_text():
    doc = parse(frame('<text:p>Same</text:p>') * 2)
    assert doc.textboxes == 'Same\n\nSame'


def test_headers_and_body_share_cell_budget():
    header = '<style:header>' + table('<text:p>H</text:p>') + '</style:header>'
    with pytest.raises(LimitExceededError, match='cell limit'):
        parse(table('<text:p>B</text:p>'), extra={'styles.xml': styles(master(header))},
              limits=Limits(max_cells=1))


def test_story_xml_nodes_share_record_budget():
    with pytest.raises(LimitExceededError, match='node limit'):
        parse(frame('<text:p>X</text:p>') * 20, limits=Limits(max_records=20))


def page_style(name, page=None, parent=None, family='paragraph', properties='', extra=''):
    attrs = f'style:name="{name}" style:family="{family}"'
    if page is not None:
        attrs += f' style:master-page-name="{page}"'
    if parent is not None:
        attrs += f' style:parent-style-name="{parent}"'
    return f'<style:style {attrs} {extra}>{properties}</style:style>'


def marked_master(name, next_name=None):
    value = master('<style:header><text:p>' + name + '</text:p></style:header>', name)
    if next_name is not None:
        value = value.replace('<style:master-page ', f'<style:master-page style:next-style-name="{next_name}" ', 1)
    return value


def content_with_styles(body, automatic):
    namespaces = ' '.join(f'xmlns:{k}="{v}"' for k, v in NS.items())
    namespaces += ' xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    return (f'<office:document-content {namespaces}><office:automatic-styles>{automatic}'
            f'</office:automatic-styles><office:body><office:text>{body}'
            '</office:text></office:body></office:document-content>')


def test_initial_reference_overrides_first_master_through_inheritance():
    defs = page_style('Base', 'Used') + page_style('Child', parent='Base')
    defs += page_style('UnusedStyle', 'unusedmaster')
    xml = styles(marked_master('unusedmaster') + marked_master('Used'), common=defs,
                 automatic=page_style('P1', 'unusedmaster'))
    content = content_with_styles('<text:p text:style-name="P1">Body</text:p>',
                                  page_style('P1', parent='Child'))
    doc = parse(content=content, extra={'styles.xml': xml})
    assert doc.headers_footers == 'Used'
    assert 'unusedmaster' not in doc.text
    assert not any('fallback' in w for w in doc.warnings)


def test_initial_fallback_is_not_replaced_by_a_later_reference():
    xml = styles(marked_master('Initial') + marked_master('Later') + marked_master('unusedmaster'),
                 common=page_style('LaterStyle', 'Later'))
    doc = parse('<text:p>First</text:p><text:p text:style-name="LaterStyle">Second</text:p>',
                extra={'styles.xml': xml})
    assert doc.headers_footers == 'Initial\n\nLater'
    assert any('implementation-defined fallback' in w for w in doc.warnings)


def test_empty_master_attribute_does_not_reactivate_inherited_master():
    xml = styles(marked_master('Initial') + marked_master('unusedmaster'),
                 common=page_style('Base', 'unusedmaster') + page_style('Child', '', 'Base'))
    doc = parse('<text:p text:style-name="Child">Body</text:p>', extra={'styles.xml': xml})
    assert doc.headers_footers == 'Initial'


def test_styles_in_cell_paragraphs_notes_frames_and_revisions_do_not_select_masters():
    defs = page_style('Active', 'Used') + page_style('Unused', 'unusedmaster')
    ghost = '<text:p text:style-name="Unused">Text</text:p>'
    body = ('<text:p text:style-name="Active">Main' + frame(ghost) + note(ghost) + '</text:p>' +
            table(ghost) + '<text:tracked-changes>' + ghost + '</text:tracked-changes>')
    doc = parse(body, extra={'styles.xml': styles(marked_master('Used') +
                                                marked_master('unusedmaster'), common=defs)})
    assert doc.headers_footers == 'Used'
    assert 'unusedmaster' not in doc.text


def test_table_master_reference_is_resolved_in_its_own_family():
    defs = page_style('Base', 'Used', family='table') + page_style('T', parent='Base', family='table')
    defs += page_style('T', 'unusedmaster')
    body = table('<text:p>Cell</text:p>').replace('<table:table>', '<table:table table:style-name="T">', 1)
    doc = parse(body, extra={'styles.xml': styles(marked_master('unusedmaster') +
                                                marked_master('Used'), common=defs)})
    assert doc.headers_footers == 'Used'


@pytest.mark.parametrize('defs', [
    '',  # Missing referenced style.
    page_style('P', parent='Missing'),
    page_style('P', parent='Q') + page_style('Q', parent='P'),
    page_style('P', 'unusedmaster') + page_style('P', 'Other'),
    page_style('P', 'unusedmaster', properties='<style:map style:condition="true" style:apply-style-name="Other"/>'),
])
def test_ambiguous_style_graph_never_falls_back_to_dumping_masters(defs):
    doc = parse('<text:p text:style-name="P">Body</text:p>', extra={'styles.xml': styles(
        marked_master('unusedmaster') + marked_master('Other'), common=defs)})
    assert doc.headers_footers == doc.textboxes == ''
    assert any('ambiguous' in w for w in doc.warnings)


@pytest.mark.parametrize('masters_xml', [marked_master('Other'),
                                        marked_master('Used') + marked_master('Used')])
def test_missing_or_duplicate_master_reference_omits_affected_stories(masters_xml):
    doc = parse('<text:p text:style-name="P">Body</text:p>',
                extra={'styles.xml': styles(masters_xml, common=page_style('P', 'Used'))})
    assert doc.headers_footers == ''
    assert any('master reference' in w for w in doc.warnings)


def test_next_chain_follows_page_evidence_only_and_cycles_do_not_duplicate():
    xml = styles(marked_master('A', 'B') + marked_master('B', 'C') +
                 marked_master('C', 'A') + marked_master('unusedmaster'))
    doc = parse('<text:p>1<text:soft-page-break/>2<text:soft-page-break/>3'
                '<text:soft-page-break/>4</text:p>', extra={'styles.xml': xml})
    assert doc.headers_footers == 'A\n\nB\n\nC'
    assert any('pagination is not computed' in w for w in doc.warnings)


@pytest.mark.parametrize('body', ['<text:p>One page</text:p>',
                                  '<text:p text:style-name="After">Trailing break</text:p>'])
def test_unreached_next_master_is_not_document_text(body):
    after = '<style:paragraph-properties fo:break-after="page"/>'
    xml = styles(marked_master('A', 'unusedmaster') + marked_master('unusedmaster'),
                 common=page_style('After', properties=after))
    doc = parse(body, extra={'styles.xml': xml})
    assert doc.headers_footers == 'A'
    assert 'unusedmaster' not in doc.text


def test_explicit_master_overrides_next_and_paragraph_next_style_is_not_usage():
    defs = page_style('AStyle', 'A', extra='style:next-style-name="GhostStyle"')
    defs += page_style('CStyle', 'C') + page_style('GhostStyle', 'unusedmaster')
    doc = parse('<text:p text:style-name="AStyle">A</text:p>'
                '<text:p text:style-name="CStyle">C</text:p>', extra={'styles.xml': styles(
                    marked_master('A', 'unusedmaster') + marked_master('C') +
                    marked_master('unusedmaster'), common=defs)})
    assert doc.headers_footers == 'A\n\nC'


def test_inherited_page_breaks_coalesce_after_and_before():
    defs = page_style('After', properties='<style:paragraph-properties fo:break-after="page"/>')
    defs += page_style('Base', properties='<style:paragraph-properties fo:break-before="page"/>')
    defs += page_style('Before', parent='Base')
    doc = parse('<text:p text:style-name="After">A</text:p>'
                '<text:p text:style-name="Before">B</text:p>', extra={'styles.xml': styles(
                    marked_master('A', 'B') + marked_master('B', 'unusedmaster') +
                    marked_master('unusedmaster'), common=defs)})
    assert doc.headers_footers == 'A\n\nB'


def test_default_style_page_break_properties_are_inherited():
    default = ('<style:default-style style:family="paragraph">'
               '<style:paragraph-properties fo:break-before="page"/></style:default-style>')
    xml = styles(marked_master('A', 'B') + marked_master('B'), common=default)
    assert parse('<text:p>A</text:p><text:p>B</text:p>',
                 extra={'styles.xml': xml}).headers_footers == 'A\n\nB'


def test_page_sequence_initial_master_and_recorded_transition():
    body = ('<text:page-sequence><text:page text:master-page-name="A"/>'
            '<text:page text:master-page-name="B"/>'
            '<text:page text:master-page-name="unusedmaster"/></text:page-sequence>'
            '<text:p>A<text:soft-page-break/>B</text:p>')
    doc = parse(body, extra={'styles.xml': styles(marked_master('unusedmaster') +
                                                marked_master('A') + marked_master('B'))})
    assert doc.headers_footers == 'A\n\nB'


def test_style_inheritance_depth_is_bounded():
    defs = ''.join(page_style(f'P{i}', parent=f'P{i+1}') for i in range(9)) + page_style('P9', 'A')
    with pytest.raises(LimitExceededError, match='style inheritance depth'):
        parse('<text:p text:style-name="P0">Body</text:p>',
              extra={'styles.xml': styles(marked_master('A'), common=defs)}, limits=Limits(max_depth=8))


def test_next_master_chain_depth_is_bounded():
    definitions = ''.join(marked_master(f'M{i}', f'M{i+1}') for i in range(9)) + marked_master('M9')
    with pytest.raises(LimitExceededError, match='next master chain depth'):
        parse('<text:p>' + 'page<text:soft-page-break/>' * 9 + '</text:p>',
              extra={'styles.xml': styles(definitions)}, limits=Limits(max_depth=8))


def test_main_stories_precede_header_stories_independently_of_master_order():
    main = ('<text:p>Main' + frame('<text:p>Main box</text:p>') +
            note('<text:p>Main footnote</text:p>') +
            note('<text:p>Main endnote</text:p>', 'endnote') + '</text:p>')
    header = ('<style:header><text:p>Header' + frame('<text:p>Header box</text:p>') +
              note('<text:p>Header footnote</text:p>') +
              note('<text:p>Header endnote</text:p>', 'endnote') + '</text:p></style:header>')
    doc = parse(main, extra={'styles.xml': styles(master(header))})
    assert doc.textboxes == 'Main box\n\nHeader box'
    assert doc.footnotes == 'Main footnote\n\nHeader footnote'
    assert doc.endnotes == 'Main endnote\n\nHeader endnote'
    assert doc.headers_footers == 'Header'


def test_unused_master_story_does_not_consume_extraction_cell_budget():
    unused = master('<style:header>' + table(frame(table('<text:p>unusedmaster</text:p>')),
                                            rows=50, columns=50) + '</style:header>', 'Unused')
    doc = parse('<text:p>Main</text:p>', extra={'styles.xml': styles(marked_master('Active') + unused)},
                limits=Limits(max_cells=1))
    assert doc.headers_footers == 'Active'
    assert doc.textboxes == ''


def test_hidden_section_neither_extracts_stories_nor_selects_its_master():
    hidden = ('<text:section text:display="none"><text:p text:style-name="Hidden">HIDDEN_TEXT' +
              frame('<text:p>HIDDEN_BOX</text:p>') + note('<text:p>HIDDEN_NOTE</text:p>') +
              '</text:p></text:section>')
    definitions = page_style('Visible', 'Used') + page_style('Hidden', 'unusedmaster')
    doc = parse(hidden + '<text:p text:style-name="Visible">Visible</text:p>', extra={'styles.xml':
                styles(marked_master('unusedmaster') + marked_master('Used'), common=definitions)})
    assert [b.text for b in doc.blocks] == ['Visible']
    assert doc.headers_footers == 'Used'
    assert doc.textboxes == doc.footnotes == ''
    assert 'HIDDEN' not in doc.text and 'unusedmaster' not in doc.text
    assert any('hidden section' in w for w in doc.warnings)


@pytest.mark.parametrize('location', ['table', 'frame', 'note', 'header'])
def test_hidden_section_in_nested_stories_is_not_scraped(location):
    hidden = ('<text:section text:display="none"><text:p>HIDDEN_TEXT' +
              frame('<text:p>HIDDEN_BOX</text:p>') + note('<text:p>HIDDEN_NOTE</text:p>') +
              '</text:p></text:section>')
    extra = {}
    if location == 'header':
        body = '<text:p>Visible</text:p>'
        extra['styles.xml'] = styles(master('<style:header>' + hidden + '</style:header>'))
    elif location == 'note':
        body = '<text:p>Visible' + note(hidden) + '</text:p>'
    else:
        body = (table if location == 'table' else frame)(hidden) + '<text:p>Visible</text:p>'
    doc = parse(body, extra=extra)
    assert doc.text == 'Visible'
    assert doc.textboxes == doc.footnotes == doc.headers_footers == ''
