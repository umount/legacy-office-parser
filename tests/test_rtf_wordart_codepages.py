"""Original CP1250/1253 WordArt inputs and literal text expectations."""
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser import Limits, parse_rtf
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.models import Paragraph
from legacy_office_parser.rtf import parse_rtf_bytes


# Bytes and Unicode expectations are authored literals, not codec-generated
# fixture text or parser-derived oracle values.
CASES = [
    (br'\ansicpg1250 ', br"\'8elu\'9d", 'Žluť'),
    (br'\ansicpg1253 ', br"\'c5\'eb\'eb\'dc\'e4\'e1", 'Ελλάδα'),
    (br'\ansicpg1250 ', br'\u381?lu\u357?', 'Žluť'),
    (br'\ansicpg1253 ', br'\u937?', 'Ω'),
    (br'\deff0{\fonttbl{\f0\fcharset238 F;}}\f0 ', br"\'8elu\'9d", 'Žluť'),
    (br'\deff0{\fonttbl{\f0\fcharset161 F;}}\f0 ', br"\'c5\'eb\'eb\'dc\'e4\'e1", 'Ελλάδα'),
    (br'\deff0{\fonttbl{\f0\cpg1250 F;}}\f0 ', br"\'8elu\'9d", 'Žluť'),
    (br'\deff0{\fonttbl{\f0\cpg1253 F;}}\f0 ', br"\'c5\'eb\'eb\'dc\'e4\'e1", 'Ελλάδα'),
]


def prop(name, value):
    return br'{\sp{\sn ' + name + br'}{\sv ' + value + b'}}'


def shape(value, before=b'', after=b'', tail=b''):
    return (br'{\shp{\*\shpinst' + prop(b'shapeType', b'136')
            + prop(b'fGtext', b'1') + prop(b'fGtextOK', b'1')
            + before + prop(b'gtextUNICODE', value) + after + b'}' + tail + b'}')


def source(header, body):
    return br'{\rtf1\ansi ' + header + br'Before\par ' + body + br'After\par}'


def parse(body, **limits):
    return parse_rtf_bytes(br'{\rtf1\ansi ' + body + b'}', Limits(**limits))


@pytest.mark.parametrize('header,value,expected', CASES)
def test_explicit_document_and_font_encoding(header, value, expected):
    doc = parse_rtf_bytes(source(header, shape(value)), Limits())
    assert doc.textboxes == expected
    assert doc.blocks == [Paragraph('Before'), Paragraph('After')]
    assert not any('WordArt' in w for w in doc.warnings)
    assert doc.to_dict()['textboxes'] == expected


@pytest.mark.parametrize('prefix,value,expected', [
    (br'\ansicpg1250 ', b'\x8elu\x9d', 'Žluť'),
    (br'\ansicpg1253 ', b'\xc5\xeb\xeb\xdc\xe4\xe1', 'Ελλάδα'),
    (br'\ansicpg1250 ', br"\'8e" + b'lu\x9d', 'Žluť'),
    (br'\ansicpg1253 ', b'\xc5' + br"\'eb\'eb" + b'\xdc\xe4\xe1', 'Ελλάδα'),
])
def test_literal_and_hex_bytes_share_the_existing_decoder(prefix, value, expected):
    assert parse(prefix + shape(value)).textboxes == expected


@pytest.mark.parametrize('cp', [1250, 1253])
@pytest.mark.parametrize('value', [br"Prefix\'81Suffix", b'Prefix\x81Suffix',
                                   br'\uc0\u-10179', br'\uc0\u-8704',
                                   br'\uc0\u0', br'\uc0\u127',
                                   br'{\u937?}', br'\ansicpg1252 X', br'\f0 X',
                                   br'\v0 X', br'\deleted0 X', br'\field X',
                                   br'\emdash X', br'\line X'])
def test_bad_bytes_or_rich_controls_reject_entire_candidate(cp, value):
    doc = parse(('\\ansicpg%d ' % cp).encode() + b'A' + shape(value) + b'B')
    assert doc.blocks == [Paragraph('AB')]
    assert doc.textboxes == '' and '\ufffd' not in doc.text


def test_unicode_fallback_ignores_undefined_bytes_and_remains_local():
    doc = parse(br'\ansicpg1253 ' + shape(br"\u937\'81")
                + shape(br'\uc0\u937') + br'\u65?')
    assert doc.textboxes == 'Ω\nΩ'
    assert doc.blocks == [Paragraph('A')]
    assert parse(br'\ansicpg1250 ' + shape(br'\u381\bin3 {x}lu\u357?')).textboxes == 'Žluť'


def test_codepage_group_and_font_restoration():
    body = (br'{\ansicpg1250 ' + shape(br"\'8elu\'9d") + b'}'
            + br'{\ansicpg1253 ' + shape(br"\'d9") + b'}'
            + shape(br"Caf\'e9"))
    assert parse(body).textboxes == 'Žluť\nΩ\nCafé'
    fonts = br'\deff0{\fonttbl{\f0\fcharset238 F;}{\f1\fcharset161 G;}}\f0 '
    body = (br'{\f1 ' + shape(br"\'d9") + b'}'
            + shape(br"\'8elu\'9d"))
    assert parse(fonts + body).textboxes == 'Ω\nŽluť'


@pytest.mark.parametrize('prefix', [br'\ansicpg99999\ansicpg1250 ',
                                    br'{\fonttbl{\f0\fcharset2 F;}}\ansicpg1253 ',
                                    br'\ansicpg1254 ', br'\ansicpg65001 '])
def test_unknown_or_unaccepted_effective_encoding_cannot_gain_eligibility(prefix):
    assert not parse(prefix + shape(br'\u937?')).textboxes


@pytest.mark.parametrize('cp', [1250, 1253])
@pytest.mark.parametrize('ancestor', [br'\v', br'\deleted', br'\object', br'\pict',
                                      br'\info', br'\shpgrp', br'\shprslt',
                                      br'\*\unknown', br'\*\do'])
def test_hidden_and_unowned_ancestry_stays_suppressed(cp, ancestor):
    doc = parse(('\\ansicpg%d ' % cp).encode() + b'A{' + ancestor
                + shape(br'\u937?') + b'}B')
    assert doc.blocks == [Paragraph('AB')]
    assert not doc.textboxes


@pytest.mark.parametrize('extra', [prop(b'fHidden', b'1'), prop(b'fBackground', b'1'),
                                  prop(b'hspNext', b'0'), prop(b'hspMaster', b'0'),
                                  prop(b'gtextUNICODE', b'Duplicate')])
def test_shape_visibility_links_and_duplicates_remain_rejected(extra):
    assert not parse(br'\ansicpg1253 ' + shape(br'\u937?', after=extra)).textboxes


def test_primary_fallback_and_independent_story_identity():
    fallback = br'{\shprslt{\*\do\dptxbx{\dptxbxtext Fallback}}}'
    primary = br'{\shptxt Primary}'
    body = shape(br'\u937?', tail=fallback) + shape(br'\u937?')
    assert parse(br'\ansicpg1253 ' + body).textboxes == 'Ω\nΩ'
    assert parse(br'\ansicpg1253 ' + shape(br'\u937?', after=primary)).textboxes == 'Primary'
    assert parse(br'\ansicpg1253 {\shp' + fallback + b'}').textboxes == 'Fallback'


@pytest.mark.parametrize('cp,unit,expected', [(1250, br"\'8e", 'Ž'),
                                             (1253, br"\'d9", 'Ω')])
def test_retained_text_budget_and_deferred_overflow(cp, unit, expected):
    prefix = ('\\ansicpg%d ' % cp).encode()
    assert parse(prefix + shape(unit), max_text_chars=1).textboxes == expected
    with pytest.raises(LimitExceededError, match='WordArt property text'):
        parse(prefix + shape(unit * 3), max_text_chars=2)
    for before in (False, True):
        gate = prop(b'fHidden', b'1')
        body = shape(unit * 8, before=gate if before else b'', after=b'' if before else gate)
        doc = parse(prefix + b'A' + body + b'B', max_text_chars=2)
        assert doc.blocks == [Paragraph('AB')] and not doc.textboxes
    assert not parse(prefix + shape(unit * 8 + br"\'81"), max_text_chars=2).textboxes
    with pytest.raises(LimitExceededError):
        parse(prefix + shape(unit) * 2, max_text_chars=2)
    with pytest.raises(LimitExceededError):
        parse(prefix + shape(unit * 8), max_records=12)
    with pytest.raises(LimitExceededError):
        parse(prefix + shape(unit), max_depth=3)


@pytest.mark.skipif(os.environ.get('RTF_WORDART_CODEPAGES_LO') != '1',
                    reason='opt-in original WordArt code-page oracle')
@pytest.mark.parametrize('header,value,expected', CASES)
def test_live_independent_codepage_text(header, value, expected, tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / 'codepage.rtf'
    path.write_bytes(source(header, shape(value)))
    original = path.read_bytes()
    sys.path.insert(0, str(root / 'tools'))
    try:
        from check_performance import bounded
    finally:
        sys.path.pop(0)
    result = bounded([sys.executable, str(root / 'tools/check_performance.py'), '--convert-child',
                      '/usr/bin/libreoffice', str(path), str(tmp_path), 'fodt'], 45)
    assert result['status'] == 'ok', result
    assert path.read_bytes() == original
    tree = ET.parse(tmp_path / 'codepage.fodt')
    ns = {'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
          'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    observed = [''.join(p.itertext()) for s in tree.findall('.//draw:custom-shape', ns)
                for p in s.findall('text:p', ns)]
    assert observed == [expected]
    assert parse_rtf(path).textboxes == expected


@pytest.mark.parametrize('style', [br'{\s1\v Hidden;}', br'{\s1\deleted Deleted;}'])
def test_inherited_style_visibility_still_blocks_candidate(style):
    assert not parse(br'\ansicpg1253{\stylesheet' + style + br'}\s1 '
                     + shape(br'\u937?')).textboxes


def test_explicit_font_codepage_keeps_existing_precedence():
    header = br'\ansicpg1250\deff0{\fonttbl{\f0\fcharset238\cpg1253 F;}}\f0 '
    assert parse(header + shape(br"\'d9")).textboxes == 'Ω'
