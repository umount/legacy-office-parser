"""Original literal expectations for the bounded Unicode WordArt extension."""
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

from legacy_office_parser import parse_rtf
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph
from legacy_office_parser.rtf import parse_rtf_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'tests/fixtures/rtf_wordart_unicode'
EXPECTED = {
    'unicode': ['Grüße Ж 😀'], 'uc-zero': ['Ж😀'], 'uc-two': ['ЖX'],
    'cp1252': ['Café €'], 'cp1251': ['Привет'], 'cp932': ['日本'],
    'scoped': ['Пр', 'Café'], 'font1251': ['Привет'], 'inherited-uc': ['ЖX'],
}


def prop(name, value):
    return br'{\sp{\sn ' + name + br'}{\sv ' + value + b'}}'


def shape(value, before=b'', after=b'', tail=b''):
    return (br'{\shp{\*\shpinst' + prop(b'shapeType', b'136')
            + prop(b'fGtext', b'1') + prop(b'fGtextOK', b'1')
            + before + prop(b'gtextUNICODE', value) + after + b'}' + tail + b'}')


def parse(body, **limits):
    return parse_rtf_bytes(br'{\rtf1\ansi ' + body + b'}', Limits(**limits))


@pytest.mark.parametrize('name', EXPECTED)
def test_authored_unicode_fixtures_match_literal_and_recorded_independent_text(name):
    source = FIXTURES/(name+'.rtf')
    report = json.loads((FIXTURES/'lo-observations.json').read_text())['files'][source.name]
    assert report['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report['lo_shape_paragraphs'] == EXPECTED[name]
    doc = parse_rtf(source)
    assert doc.textboxes == '\n'.join(EXPECTED[name])
    assert doc.blocks == [Paragraph('Before'), Paragraph('After')]


@pytest.mark.parametrize('raw,expected', [
    (br'\u1040?', 'А'), (br'\uc0\u65', 'A'), (b'\x80', '€'),
    (br'\u1046\{X', 'ЖX'), (br'\u1046\par X', 'ЖX'),
    (br'\u1046\bin3 {x}X', 'ЖX'), (br'\uc2\u1046??X', 'ЖX'),
    (br'\uc2\u1046\'3f?X', 'ЖX'),
    (br'\u-10179?\u-8704?', '😀'), (br'\uc0\u55357\u56832', '😀'),
    (br'\u1046?', 'Ж'), (br'\uc4\u1046?', 'Ж'),
])
def test_unicode_fallback_uses_existing_lexer_token_semantics(raw, expected):
    assert parse(shape(raw)).textboxes == expected


@pytest.mark.parametrize('raw', [
    br'\u-10179?', br'\u-8704?', br'\u-10179?X', br'\u-10179?\u-10179?\u-8704?',
    br'\u-10179?{\u-8704?}', br'\u-32769?', br'\u65536?', br'\u?',
    br'\uc-1 X', br'\uc9999999999 X', br'\uc X', b'\x81',
    br'\uc0\u0', br'\uc0\u127', br'\uc0\u10', br'\ansicpg1251 X',
    br'\f0 X', br'{\uc0\u1046}', br'\upr X', br'\field X',
])
def test_invalid_or_unsupported_property_rejected_whole_without_replacement(raw):
    doc = parse(b'A' + shape(b'Prefix'+raw+b'Suffix') + b'B')
    assert doc.blocks == [Paragraph('AB')]
    assert doc.textboxes == ''
    assert any('WordArt' in warning for warning in doc.warnings)
    assert '\ufffd' not in doc.text


def test_fallback_count_and_decoder_state_do_not_escape_value_or_shape():
    body = (br'\uc1 ' + shape(br'\uc0\u1046') + shape(br'\u1046?')
            + br'\u65?{\ansicpg1251 ' + shape(br"\'cf") + b'}'
            + shape(br"\'e9") + br'\u66?')
    doc = parse(body)
    assert doc.blocks == [Paragraph('AB')]
    assert doc.textboxes == 'Ж\nЖ\nП\né'
    # A dangling high surrogate cannot pair with a later property's low half.
    assert parse(shape(br'\u-10179?') + shape(br'\u-8704?')).textboxes == ''


def test_dbcs_decoder_spans_hex_and_literal_bytes_and_rejects_incomplete_sequence():
    assert parse(br'\ansicpg932 ' + shape(br"\'93"+b'\xfa')).textboxes == '日'
    assert parse(br'\ansicpg932 ' + shape(br"\'93\'fa\'96\'7b"), max_text_chars=2).textboxes == '日本'
    for value in [br"\'93", br"\'93\u65?", br"\'93\uc0 A"]:
        doc = parse(br'\ansicpg932 A' + shape(value) + b'B')
        assert doc.blocks == [Paragraph('AB')]
        assert not doc.textboxes


@pytest.mark.parametrize('prefix', [br'\ansicpg65001 ', br'\ansicpg1254 ',
                                    br'\ansicpg37 ', br'\ansicpg99999 '])
def test_unproven_or_uncertain_codepages_remain_omitted(prefix):
    assert parse(prefix + shape(br'\u1046?')).textboxes == ''


@pytest.mark.parametrize('ancestor', [br'\v', br'\deleted', br'\object', br'\pict',
                                      br'\*\unknown', br'\shpgrp', br'\shprslt'])
def test_unicode_decoder_does_not_reopen_suppressed_or_unowned_shapes(ancestor):
    doc = parse(b'A{' + ancestor + shape(br'\u1046?') + b'}B')
    assert doc.blocks == [Paragraph('AB')]
    assert not doc.textboxes


def test_unicode_ignores_fallback_shape_copy_and_retains_independent_shapes():
    fallback = br'{\shprslt{\shp{\*\shpinst{\shptxt Duplicate}}}}'
    doc = parse(shape(br'\u1046?', tail=fallback) + shape(br'\u1046?'))
    assert doc.textboxes == 'Ж\nЖ'
    assert 'Duplicate' not in doc.text


@pytest.mark.parametrize('first', [False, True])
@pytest.mark.parametrize('name,value', [(b'fHidden', b'1'), (b'unknown', b'0'),
                                       (b'fGtext', b'0'), (b'shapeType', b'202')])
def test_unicode_overflow_is_deferred_until_final_eligibility(first, name, value):
    gate = prop(name, value)
    body = shape(br'\u1046?'*8, before=gate if first else b'', after=b'' if first else gate)
    if name in {b'fGtext', b'shapeType'}:
        body = body.replace(prop(name, b'1' if name == b'fGtext' else b'136'), b'', 1)
    doc = parse(b'A' + body + b'B', max_text_chars=2)
    assert doc.blocks == [Paragraph('AB')]
    assert not doc.textboxes


@pytest.mark.parametrize('suffix', [br'\u-10179?', br'\uc-1 X', b'\x81', br'{\u65?}'])
def test_invalid_tail_after_decoded_overflow_still_rejects(suffix):
    doc = parse(b'A' + shape(br'\u1046?'*8 + suffix) + b'B', max_text_chars=2)
    assert doc.blocks == [Paragraph('AB')]
    assert not doc.textboxes


def test_decoded_character_and_shared_projection_budgets():
    assert parse(shape(br'\u-10179?\u-8704?'), max_text_chars=1).textboxes == '😀'
    assert parse(br'\ansicpg932 '+shape(br"\'93\'fa"), max_text_chars=1).textboxes == '日'
    for body, limits in [(shape(br'\u1046?'*3), {'max_text_chars': 2}),
                         (shape(br'\u1046?')*2, {'max_text_chars': 2}),
                         (b'A'+shape(br'\u1046?'*2), {'max_text_chars': 2}),
                         (shape(br'\u1046?'*65537), {'max_records': 300000}),
                         (shape(br'\u1046?'*20), {'max_records': 20}),
                         (shape(br'\u1046?'), {'max_depth': 3})]:
        with pytest.raises(LimitExceededError):
            parse(body, **limits)


def test_overflow_reader_scratch_remains_bounded(monkeypatch):
    from legacy_office_parser.rtf import _PropertyText
    original = _PropertyText.text
    overflow_seen = False

    def checked(self, text):
        nonlocal overflow_seen
        original(self, text)
        assert self.size <= 65536
        assert len(self.buffer) <= 4096
        if self.overflow:
            overflow_seen = True
            assert not self.parts

    monkeypatch.setattr(_PropertyText, 'text', checked)
    doc = parse(shape(br'\u1046?'*70000, after=prop(b'fHidden', b'1')),
                max_records=300000)
    assert overflow_seen and not doc.textboxes


@pytest.mark.skipif(os.environ.get('RTF_UNICODE_LO') != '1', reason='opt-in original Unicode fixtures')
@pytest.mark.parametrize('name', EXPECTED)
def test_live_independent_unicode_fixture(name, tmp_path):
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
    ns = {'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
          'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    texts = [''.join(p.itertext()) for s in tree.findall('.//draw:custom-shape', ns)
             for p in s.findall('text:p', ns)]
    assert texts == EXPECTED[name]
    assert parse_rtf(source).textboxes == '\n'.join(EXPECTED[name])
