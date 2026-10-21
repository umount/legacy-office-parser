"""Authored fallback boundary probes; omission is not claimed as recovery support."""
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser import parse_rtf
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/rtf_fallback_text'
TEXT = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
DRAW = '{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}'
BOXES = {
    'standalone': ['Legacy control'],
    'modern-primary': ['Primary text'],
    'no-instructions': [],
    'empty-instructions': [],
    'typed-no-primary': [],
    'empty-primary': [''],
    'primary-before': ['Primary text'],
    'primary-after': ['Primary text'],
    'group-fallback': [],
}


def parse(body, **limits):
    return parse_rtf_bytes(b'{\\rtf1\\ansi ' + body + b'}', Limits(**limits))


def fallback(content=b'Fallback'):
    return (br'{\shprslt{\*\do\dptxbx{\dptxbxtext ' + content + b'}}}')


@pytest.mark.parametrize('name', BOXES)
def test_recorded_shape_controls_and_unresolved_fallback_boundary(name):
    source = FIXTURES / (name + '.rtf')
    observations = json.loads((FIXTURES/'lo-observations.json').read_text())
    recorded = observations['files'][source.name]
    assert recorded['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert recorded['lo_textbox_paragraphs'] == BOXES[name]
    document = parse_rtf(source)
    assert document.blocks == [Paragraph('Before'), Paragraph('After')]
    assert document.textboxes == '\n'.join(BOXES[name])
    # These assertions pin the current conservative boundary. They do not
    # certify that fallback-only content is universally empty or irrelevant.
    assert document.warnings


@pytest.mark.parametrize('ancestor', [br'\object', br'\pict', br'\info', br'\sp',
                                      br'\background', br'\*\unknown'])
@pytest.mark.parametrize('primary_first', [False, True])
def test_skipped_ancestor_cannot_be_reopened_by_fallback_or_primary(ancestor, primary_first):
    primary = br'{\*\shpinst{\shptxt Primary}}'
    alternate = fallback(br'Fallback{\shptxt Escape}{\header Header}{\footnote Note}')
    contents = primary + alternate if primary_first else alternate + primary
    result = parse(b'A{' + ancestor + br'{\shp ' + contents + b'}}B')
    assert result.blocks == [Paragraph('AB')]
    assert result.textboxes == result.headers_footers == result.footnotes == ''


def test_nested_fallback_cannot_own_or_suppress_a_sibling_primary():
    nested = fallback(br'{\shp{\*\shpinst{\shptxt Nested}}}' + fallback(b'Deep'))
    result = parse(br'{\shp ' + nested + br'{\*\shpinst{\shptxt Kept}}}'
                   + br'{\shp{\*\shpinst{\shptxt Independent}}}')
    assert result.textboxes == 'Kept\nIndependent'


def test_fallback_controls_cannot_modify_tables_stories_or_fonts():
    decoy = (br'{\fonttbl{\f0\fcharset204 Changed;}}\trowd\cellx10 X\cell\row'
             br'{\header Bad}{\footnote Bad}{\shptxt Bad}')
    result = parse(br'\trowd\cellx100\intbl A{\shp ' + fallback(decoy)
                   + br'}B\cell\row{\header H{\shp ' + fallback(decoy) + br'}T}')
    assert result.blocks == [Table([[Cell('AB')]])]
    assert result.headers_footers == 'HT'
    assert result.textboxes == result.footnotes == result.endnotes == ''


def test_fallback_scratch_is_bounded_and_binary_payload_is_opaque():
    assert parse(b'A{\\shp ' + fallback(b'x' * 32000) + b'}B', max_text_chars=2).text == 'AB'
    payload = br'{\shptxt Escape}\header injected'
    result = parse(b'A{\\shp ' + fallback(b'\\bin' + str(len(payload)).encode() + b' ' + payload) + b'}B')
    assert result.text == 'AB' and not result.textboxes
    for limits in ({'max_depth': 2}, {'max_records': 5}, {'max_stream_bytes': 20}):
        with pytest.raises(LimitExceededError):
            parse(b'A{\\shp ' + fallback(b'x' * 100) + b'}B', **limits)
    with pytest.raises(InvalidDocumentError):
        parse(fallback(br'\bin99999 x'))


def test_concrete_alternative_probe_is_recorded_without_claiming_implementation():
    source = FIXTURES/'wordart-property.rtf'
    report = json.loads((FIXTURES/'lo-observations.json').read_text())['files'][source.name]
    assert report['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report['lo_shape_paragraphs'] == ['Original WordArt']
    assert br'{\sn gtextUNICODE}{\sv Original WordArt}' in source.read_bytes()
    assert 'Original WordArt' not in report['parser_text']


@pytest.mark.skipif(os.environ.get('RTF_FALLBACK_LO') != '1', reason='opt-in authored LibreOffice boundary probes')
@pytest.mark.parametrize('name', [*BOXES, 'wordart-property', 'break-controls'])
def test_live_independent_conversion(name, tmp_path):
    sys.path.insert(0, str(ROOT/'tools'))
    try:
        from check_performance import bounded
    finally:
        sys.path.pop(0)
    source = FIXTURES/(name+'.rtf')
    result = bounded([sys.executable, str(ROOT/'tools/check_performance.py'), '--convert-child',
                      '/usr/bin/libreoffice', str(source), str(tmp_path), 'fodt'], 45)
    assert result['status'] == 'ok', result
    tree = ET.parse(tmp_path/(name+'.fodt'))
    if name in BOXES:
        assert [''.join(p.itertext()) for p in tree.findall('.//'+DRAW+'text-box//'+TEXT+'p')] == BOXES[name]
    elif name == 'wordart-property':
        assert [''.join(p.itertext()) for s in tree.findall('.//'+DRAW+'custom-shape')
                for p in s.findall(TEXT+'p')] == ['Original WordArt']
    else:
        assert [''.join(p.itertext()) for p in tree.findall('.//'+TEXT+'p')] == ['AB', 'CD']
