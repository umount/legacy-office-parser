"""Original RTF/ODT fixtures: literal expectations, independent XML and LO evidence."""
import importlib.util
import os
from pathlib import Path
import re
import sys
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser import parse

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'tests/fixtures/paragraph_headings'
spec = importlib.util.spec_from_file_location('paragraph_heading_reference', ROOT / 'reference.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
ORACLE_CASES = [
    ('authored.odt', 'odt/authored.docx', reference.EXPECTED),
    ('explicit.rtf', 'explicit/explicit.docx', reference.EXPLICIT),
    ('authored.rtf', 'rtf/authored.docx', reference.RTF_EXPORT),
]


# Compatibility policy is separate from source/LO evidence. These literals are
# intentionally NOT supplied to the independent saved or live readback tests.
INFERENCE_WARNING = 'RTF heading levels inferred from built-in style names.'
PARSER_RTF_EXPORT = {
    'Heading one specimen': 1,
    'Heading two specimen': 2,
    'Ordinary body specimen': None,
    'Inherited heading specimen': 1,
    'Direct body override specimen': 1,
    'Custom body style specimen': 1,
    'Direct outline three specimen': None,
    'Cell heading specimen': 2,
    'Header heading specimen': 2,
}
PARSER_EXPLICIT = {**reference.EXPLICIT, 'Misleading style name specimen': 1}
PARSER_CASES = [
    ('authored.odt', reference.EXPECTED, False),
    ('explicit.rtf', PARSER_EXPLICIT, True),
    ('authored.rtf', PARSER_RTF_EXPORT, True),
]


def test_original_docx_source_has_literal_intended_levels():
    source = REPO / 'tests/fixtures/doc_headings/authored.docx'
    assert reference.docx_levels(source) == reference.EXPECTED


def test_saved_odt_elements_and_style_chain_are_independent_evidence():
    levels, elements, styles = reference.odt_evidence(ROOT / 'authored.odt')
    assert levels == reference.EXPECTED
    t, s = reference.T, reference.S
    inherited = elements['Inherited heading specimen']
    body = elements['Direct body override specimen']
    assert inherited[0] == f'{{{t}}}h'
    assert body[0] == f'{{{t}}}p'
    assert inherited[1][f'{{{t}}}style-name'] == body[1][f'{{{t}}}style-name']
    assert f'{{{t}}}outline-level' not in body[1]
    child = styles['Research_20_inherited']
    assert child[f'{{{s}}}parent-style-name'] == 'Heading_20_1'
    assert styles['Heading_20_1'][f'{{{s}}}default-outline-level'] == '1'
    assert styles['Research_20_body_20_child'][f'{{{s}}}default-outline-level'] == ''
    # Check XML ownership, not just a text-to-level dictionary.
    with ZipFile(ROOT / 'authored.odt') as archive:
        content = ET.fromstring(archive.read('content.xml'))
        master = ET.fromstring(archive.read('styles.xml'))
    ns = {'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0', 't': t, 's': s}
    assert [p.text for p in content.findall('.//table:table-cell/t:h', ns)] == [
        'Cell heading specimen']
    assert [p.text for p in master.findall('.//s:header/t:h', ns)] == [
        'Header heading specimen']


def test_original_rtf_has_explicit_style_and_direct_wire_evidence():
    raw = (ROOT / 'explicit.rtf').read_text('ascii')
    # Exact clauses are intentional: this is source evidence, not a second RTF parser.
    for clause in (
        r'{\s10\sbasedon0\outlinelevel0 Research first;}',
        r'{\s11\sbasedon0\outlinelevel1 Research second;}',
        r'{\s20\sbasedon10 Research inherited;}',
        r'{\s21\sbasedon10\outlinelevel9 Research body child;}',
        r'{\s30\sbasedon0 Heading 1;}',
        r'\pard\s10 Heading one specimen\par',
        r'\pard\s11 Heading two specimen\par',
        r'\pard\s0 Ordinary body specimen\par',
        r'\pard\s20 Inherited heading specimen\par',
        r'\pard\s20\outlinelevel9 Direct body override specimen\par',
        r'\pard\s21 Custom body style specimen\par',
        r'\pard\s0\outlinelevel2 Direct outline three specimen\par',
        r'\pard\intbl\s11 Cell heading specimen\cell\row',
        r'{\header\pard\s11 Header heading specimen\par}',
        r'\pard\s30 Misleading style name specimen\par',
    ):
        assert raw.count(clause) == 1
    assert raw.count(r'\outlinelevel') == 5
    for text in reference.EXPLICIT:
        assert raw.count(text) == 1


def test_lo_rtf_export_loss_is_visible_in_raw_controls_not_parser_output():
    raw = (ROOT / 'authored.rtf').read_text('ascii')
    assert r'\outlinelevel' not in raw
    assert r'{\s1\sbasedon0\snext1 Heading 1;}' in raw
    assert r'{\s2\sbasedon0\snext2 Heading 2;}' in raw
    assert r'{\s20\sbasedon1\snext20 Research inherited;}' in raw
    assert r'{\s21\sbasedon1\snext21 Research body child;}' in raw
    # Header also occurs in LO's ignorable pgdsctbl; inspect actual paragraph runs.
    selected = {}
    for match in re.finditer(r'\\pard\\plain\s+\\s(\d+)([^{}]*)\{\\loch\s*([^{}]+)\}', raw):
        style, controls, text = match.groups()
        text = text.strip()
        if text in reference.RTF_EXPORT:
            selected[text] = int(style)
            assert r'\outlinelevel' not in controls
    assert selected == {
        'Heading one specimen': 1, 'Heading two specimen': 2,
        'Ordinary body specimen': 0, 'Inherited heading specimen': 20,
        'Direct body override specimen': 20, 'Custom body style specimen': 21,
        'Direct outline three specimen': 0, 'Cell heading specimen': 2,
        'Header heading specimen': 2,
    }


@pytest.mark.parametrize('filename,readback,expected', ORACLE_CASES)
def test_saved_independent_docx_readback(filename, readback, expected):
    assert reference.docx_levels(ROOT / 'readback' / readback) == expected


def assert_public_headings(path, expected):
    document = parse(path)
    result = document.to_dict()
    found, owners = {}, {}

    def walk(blocks, owner):
        for block in blocks:
            if block['kind'] == 'paragraph':
                text = block['text']
                if not text:
                    continue
                assert text not in found, f'duplicate paragraph: {text}'
                found[text] = block.get('heading_level')
                owners[text] = owner
                if found[text] is None:
                    assert 'heading_level' not in block
            else:
                for row in block['rows']:
                    for cell in row:
                        walk(cell.get('blocks', []), owner + '/table')

    walk(result['blocks'], 'main')
    for story, blocks in result.get('story_blocks', {}).items():
        walk(blocks, story)
    assert found == expected
    assert owners['Cell heading specimen'] == 'main/table'
    assert owners['Header heading specimen'] == 'headers_footers'
    for text in expected:
        assert document.text.count(text) == 1
    return document


@pytest.mark.parametrize('filename,expected,inferred', PARSER_CASES)
def test_parser_compatibility_levels_and_inference_warning(filename, expected, inferred):
    document = assert_public_headings(ROOT / filename, expected)
    assert document.warnings.count(INFERENCE_WARNING) == int(inferred)


def test_parser_policy_differences_from_oracle_are_explicit_and_exhaustive():
    assert {text: (reference.RTF_EXPORT[text], level)
            for text, level in PARSER_RTF_EXPORT.items()
            if level != reference.RTF_EXPORT[text]} == {
        'Heading one specimen': (None, 1),
        'Heading two specimen': (None, 2),
        'Inherited heading specimen': (None, 1),
        'Direct body override specimen': (None, 1),
        'Custom body style specimen': (None, 1),
        'Cell heading specimen': (None, 2),
        'Header heading specimen': (None, 2),
    }
    assert {text: (reference.EXPLICIT[text], level)
            for text, level in PARSER_EXPLICIT.items()
            if level != reference.EXPLICIT[text]} == {
        'Misleading style name specimen': (None, 1),
    }


@pytest.mark.parametrize('location', ['paragraph', 'style'])
def test_explicit_body_outline_overrides_exact_heading_style_name(tmp_path, location):
    raw = (ROOT / 'explicit.rtf').read_text('ascii')
    if location == 'paragraph':
        before = r'\pard\s30 Misleading style name specimen\par'
        after = r'\pard\s30\outlinelevel9 Misleading style name specimen\par'
    else:
        before = r'{\s30\sbasedon0 Heading 1;}'
        after = r'{\s30\sbasedon0\outlinelevel9 Heading 1;}'
    assert raw.count(before) == 1
    target = tmp_path / 'explicit-body.rtf'
    target.write_text(raw.replace(before, after), encoding='ascii')
    # Literal body expectation, not inferred from the parser. The source change
    # removes the sole compatibility difference from the original explicit RTF.
    assert_public_headings(target, reference.EXPLICIT)


def test_odt_style_name_and_default_outline_do_not_promote_plain_paragraph(tmp_path):
    # Both explicit h and plain p select the exact same named heading style.
    # The default-outline-level is an editor assignment hint, not a p override.
    target = tmp_path / 'plain-style.odt'
    with ZipFile(ROOT / 'authored.odt') as source, ZipFile(target, 'w') as output:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == 'content.xml':
                root = ET.fromstring(data)
                for p in root.iter(f'{{{reference.T}}}p'):
                    if p.text == 'Ordinary body specimen':
                        p.set(f'{{{reference.T}}}style-name', 'Heading_20_1')
                data = ET.tostring(root)
            output.writestr(info, data)
    assert reference.odt_evidence(target)[0] == reference.EXPECTED
    assert_public_headings(target, reference.EXPECTED)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in bounded LibreOffice reference conversion')
@pytest.mark.parametrize('filename,readback,expected', ORACLE_CASES)
def test_live_libreoffice_readback_is_strict(tmp_path, filename, readback, expected):
    office = Path('/usr/bin/libreoffice')
    if not office.is_file():
        pytest.skip('LibreOffice unavailable')
    # Use the required bounded helper: private process group, wall/CPU/memory limits.
    helper_spec = importlib.util.spec_from_file_location(
        'heading_conversion_bounds', REPO / 'tools/check_performance.py')
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    run = helper.bounded([
        sys.executable, str(REPO / 'tools/check_performance.py'), '--convert-child',
        str(office), str((ROOT / filename).resolve()), str(tmp_path.resolve()),
        'docx:Office Open XML Text',
    ], 90)
    assert run['status'] == 'ok', run
    converted = tmp_path / (Path(filename).stem + '.docx')
    assert converted.is_file(), 'converter returned success without output'
    # No blanket missing-heading allowance: authored.rtf has already lost outlines
    # on export; explicit.rtf and authored.odt must retain every intended heading.
    assert reference.docx_levels(converted) == expected


@pytest.mark.parametrize('name,expected,header_level', [
    ('explicit-rtf', reference.EXPLICIT, 2),
    ('authored-rtf', reference.RTF_EXPORT, None),
    ('authored-odt', reference.EXPECTED, 2),
])
def test_saved_lo25_readbacks_preserve_levels_and_prove_header_ownership(
        name, expected, header_level):
    evidence = reference.docx_evidence(ROOT / 'readback/lo25' / (name + '.docx'))
    assert evidence['levels'] == expected
    if name.endswith('rtf'):
        assert evidence['headers'] == [
            {'part': 'word/header1.xml', 'variant': 'even', 'paragraphs': []},
            {'part': 'word/header2.xml', 'variant': 'default',
             'paragraphs': [('Header heading specimen', header_level)]},
            {'part': 'word/header3.xml', 'variant': 'first',
             'paragraphs': [('Header heading specimen', header_level)]},
        ]
    else:
        assert evidence['headers'] == [
            {'part': 'word/header1.xml', 'variant': 'default',
             'paragraphs': [('Header heading specimen', 2)]},
        ]


@pytest.mark.parametrize('mutation,message', [
    ('body_duplicate', 'duplicate body/table paragraph'),
    ('cell_duplicate', 'duplicate body/table paragraph'),
    ('header_duplicate', 'duplicate or extra paragraph within header part'),
    ('header_level', 'header copies disagree'),
    ('header_text', 'unexpected header text'),
    ('header_in_body', 'header text in body/table'),
    ('cell_in_body', 'cell heading outside table cell'),
    ('header_in_table', 'header paragraph in nested container'),
    ('wrong_relationship', 'wrong header relationship type'),
    ('unreferenced_header', 'unreferenced header part'),
    ('duplicate_variant', 'duplicate header variant'),
    ('empty_default', 'non-even header unexpectedly empty'),
])
def test_header_copy_policy_rejects_corruption(tmp_path, mutation, message):
    from copy import deepcopy

    with ZipFile(ROOT / 'readback/lo25/explicit-rtf.docx') as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    w = '{' + reference.W + '}'
    ns = reference.NS
    document = ET.fromstring(parts['word/document.xml'])
    body = document.find('w:body', ns)
    header = ET.fromstring(parts['word/header3.xml'])
    rels = ET.fromstring(parts['word/_rels/document.xml.rels'])
    if mutation == 'body_duplicate':
        body.insert(1, deepcopy(body.find('w:p', ns)))
    elif mutation == 'cell_duplicate':
        cell = body.find('.//w:tc', ns)
        cell.append(deepcopy(cell.find('w:p', ns)))
    elif mutation == 'header_duplicate':
        header.append(deepcopy(header.find('w:p', ns)))
    elif mutation == 'header_level':
        ET.SubElement(header.find('w:p/w:pPr', ns), w + 'outlineLvl', {w + 'val': '9'})
    elif mutation == 'header_text':
        header.find('.//w:t', ns).text = 'Altered header specimen'
    elif mutation == 'header_in_body':
        body.insert(0, deepcopy(header.find('w:p', ns)))
    elif mutation == 'cell_in_body':
        cell = body.find('.//w:tc', ns)
        paragraph = cell.find('w:p', ns)
        cell.remove(paragraph)
        body.insert(0, paragraph)
    elif mutation == 'header_in_table':
        paragraph = header.find('w:p', ns)
        header.remove(paragraph)
        cell = ET.SubElement(ET.SubElement(ET.SubElement(header, w + 'tbl'), w + 'tr'),
                             w + 'tc')
        cell.append(paragraph)
    elif mutation == 'wrong_relationship':
        next(r for r in rels if r.get('Target') == 'header3.xml').set('Type', 'wrong')
    elif mutation == 'unreferenced_header':
        parts['word/header4.xml'] = parts['word/header3.xml']
    elif mutation == 'duplicate_variant':
        document.find('.//w:headerReference[@w:type="first"]', ns).set(w + 'type', 'default')
    elif mutation == 'empty_default':
        default = ET.fromstring(parts['word/header2.xml'])
        default.find('.//w:t', ns).text = ''
        parts['word/header2.xml'] = ET.tostring(default)
    parts['word/document.xml'] = ET.tostring(document)
    parts['word/header3.xml'] = ET.tostring(header)
    parts['word/_rels/document.xml.rels'] = ET.tostring(rels)
    target = tmp_path / 'corrupt.docx'
    with ZipFile(target, 'w') as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    with pytest.raises(AssertionError, match=message):
        reference.docx_levels(target)
