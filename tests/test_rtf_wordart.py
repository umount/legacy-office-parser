"""Literal expectations for the strict explicit WordArt property subset."""
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
from legacy_office_parser.models import Cell, Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/rtf_fallback_text'


def prop(name, value):
    return br'{\sp{\sn ' + name + br'}{\sv ' + value + b'}}'


def shape(text=b'Art', extra=b'', prefix=b'', tail=b''):
    return (br'{\shp ' + prefix + br'{\*\shpinst' + prop(b'shapeType', b'136')
            + prop(b'fGtext', b'1') + prop(b'fGtextOK', b'1')
            + prop(b'gtextUNICODE', text) + extra + b'}' + tail + b'}')


def parse(body, **limits):
    return parse_rtf_bytes(br'{\rtf1\ansi ' + body + b'}', Limits(**limits))


def test_independent_explicit_enabled_fixture():
    path = FIXTURES/'wordart-explicit.rtf'
    record = json.loads((FIXTURES/'lo-observations.json').read_text())['files'][path.name]
    assert record['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record['lo_shape_paragraphs'] == ['Original WordArt']
    doc = parse_rtf(path)
    assert doc.blocks == [Paragraph('Before'), Paragraph('After')]
    assert doc.textboxes == 'Original WordArt'


def test_literal_escape_order_and_independent_identity():
    doc = parse(shape(br'A\{B\}\\C\'21') + shape(br'A\{B\}\\C\'21'))
    assert doc.textboxes == 'A{B}\\C!\nA{B}\\C!'
    properties = (prop(b'gtextUNICODE', b'Ordered') + prop(b'fGtextOK', b'1')
                  + prop(b'fGtext', b'1') + prop(b'shapeType', b'136'))
    assert parse(br'{\shp{\*\shpinst' + properties + b'}}').textboxes == 'Ordered'


@pytest.mark.parametrize('name,value', [
    (b'shapeType', b'202'), (b'shapeType', b'137'), (b'fGtext', b'0'),
    (b'fGtextOK', b'0'), (b'fHidden', b'1'), (b'fBackground', b'1'),
    (b'fIsButton', b'1'), (b'hspNext', b'0'), (b'hspMaster', b'0'),
    (b'lTxid', b'0'), (b'gtextRTF', b'Other'), (b'pihlShape', b'URL'),
    (b'unknown', b'Other'), (b'gtextSize', b'--1'), (b'gtextSize', b'2147483648'),
    (b'gtextSize', b'1 '), (b'gtextSize', b'+1'), (b'gtextSize', b''),
])
def test_duplicate_competing_unknown_and_malformed_properties_reject(name, value):
    assert parse(shape(extra=prop(name, value))).textboxes == ''


@pytest.mark.parametrize('name', [b'shapeType', b'fGtext', b'fGtextOK'])
def test_required_property_cannot_be_inferred(name):
    source = shape().replace(prop(name, b'136' if name == b'shapeType' else b'1'), b'')
    assert parse(source).textboxes == ''


@pytest.mark.parametrize('value', [br'\u1040?', br'\uc0\u65', b'\x80', b'\t',
                                  br'A{B}', br'A\line B', br'\bin3 xyz',
                                  br'{\shptxt Escape}', br'\v0 Secret', br'\field X'])
def test_nonflat_nonascii_or_control_bearing_value_is_not_scraped(value):
    result = parse(shape(value))
    assert result.textboxes == ''
    assert result.blocks == []


@pytest.mark.parametrize('ancestor', [br'\object', br'\pict', br'\info', br'\sp',
                                      br'\background', br'\*\unknown', br'\shpgrp',
                                      br'\shprslt', br'\*\do', br'\v', br'\deleted'])
def test_no_ancestor_suppression_or_group_ownership_escape(ancestor):
    doc = parse(b'A{' + ancestor + shape() + b'}B')
    assert doc.textboxes == ''
    assert doc.blocks == [Paragraph('AB')]


@pytest.mark.parametrize('primary', [br'{\shptxt Primary}', br'{\shptxt}'])
@pytest.mark.parametrize('first', [False, True])
def test_any_competing_primary_rejects_property_without_changing_primary(primary, first):
    source = shape(extra=primary) if not first else shape(prefix=primary)
    assert parse(source).textboxes == ('Primary' if b'Primary' in primary else '')


def test_fallback_is_opaque_and_does_not_supply_properties():
    alternate = br'{\shprslt{\*\do\dptxbx{\dptxbxtext Duplicate}}}'
    assert parse(shape(tail=alternate)).textboxes == 'Art'
    assert parse(shape(prefix=alternate)).textboxes == 'Art'
    absent = shape().replace(prop(b'fGtext', b'1'), b'')
    assert parse(absent[:-1] + br'{\shprslt' + prop(b'fGtext', b'1') + b'}}').textboxes == ''


def test_nested_shapes_do_not_borrow_properties_and_siblings_survive():
    assert parse(shape(extra=shape(b'Nested')) + shape(b'Sibling')).textboxes == 'Sibling'
    assert parse(shape(extra=prop(b'gtextUNICODE', b'Art'))).textboxes == ''


def test_tables_headers_and_structured_stories_preserved():
    source = (br'\trowd\cellx100\intbl A' + shape() + br'B\cell\row'
              br'{\header H' + shape(b'HeaderArt') + br'T}'
              br'{\shp{\*\shpinst{\shptxt\trowd\cellx10 X\cell\row}}}')
    doc = parse(source)
    assert doc.blocks == [Table([[Cell('AB')]])]
    assert doc.headers_footers == 'HT'
    assert doc.textboxes == 'Art\nHeaderArt\nX'
    assert doc.story_blocks['textboxes'] == [Paragraph('Art'), Paragraph('HeaderArt'),
                                           Table([[Cell('X')]])]


def test_shared_text_and_lexical_limits_and_fixed_property_bound():
    assert parse(shape(b'AB'), max_text_chars=2).textboxes == 'AB'
    for body, limits in [(shape(b'ABC'), {'max_text_chars': 2}),
                         (b'X'+shape(b'AB'), {'max_text_chars': 2}),
                         (shape(b'AB')*2, {'max_text_chars': 4}),
                         (shape(b'x'*65537), {}),
                         (shape(), {'max_records': 10}),
                         (shape(), {'max_depth': 3})]:
        with pytest.raises(LimitExceededError):
            parse(body, **limits)
    assert not parse(shape(extra=prop(b'gtextFont', b'x'*129))).textboxes


def test_wrong_envelope_encoding_and_parameter_do_not_emit_property_text():
    assert not parse(shape().replace(br'\shp ', br'\shp1 ', 1)).textboxes
    assert not parse(br'\ansicpg37 ' + shape()).textboxes
    assert not parse(br'\ansicpg65001 ' + shape()).textboxes
    assert not parse(br'{\*\shp' + shape()[5:]).textboxes
    assert not parse(br'{\shp{\*\shpinst}' + shape()[6:]).textboxes


def test_rejected_nested_property_grammar_is_bounded_and_warns():
    malformed = shape(extra=prop(b'gtextSize', b'{\v0 x}'))
    assert not parse(malformed).textboxes
    assert any('WordArt' in w for w in parse(malformed).warnings)
    deep = shape(extra=b'{'*1000 + b'x' + b'}'*1000)
    assert not parse(deep, max_depth=1100).textboxes
    assert parse(shape(b'')).textboxes == ''


@pytest.mark.parametrize('first', [False, True])
@pytest.mark.parametrize('size,limits', [(65537, {}), (64, {'max_text_chars': 2})])
@pytest.mark.parametrize('name,value', [
    (b'fGtext', b'0'), (b'fGtextOK', b'0'), (b'fHidden', b'1'),
    (b'shapeType', b'202'), (b'unknown', b'1'), (b'hspNext', b'1'),
])
def test_ineligible_oversize_property_does_not_reject_valid_body(first, size, limits, name, value):
    properties = {b'shapeType': b'136', b'fGtext': b'1', b'fGtextOK': b'1'}
    properties.pop(name, None)
    gate = prop(name, value)
    text = prop(b'gtextUNICODE', b'x'*size)
    payload = b''.join(prop(k, v) for k, v in properties.items())
    payload += gate + text if first else text + gate
    doc = parse(b'A' + br'{\shp{\*\shpinst' + payload + b'}}B', **limits)
    assert doc.blocks == [Paragraph('AB')]
    assert doc.textboxes == ''


@pytest.mark.parametrize('suffix', [b'\x80', br'\u65?', br'{\v0 X}', br'\bin1 x'])
def test_invalid_value_tail_after_overflow_cannot_promote_candidate(suffix):
    doc = parse(b'A' + shape(b'x'*64 + suffix) + b'B', max_text_chars=2)
    assert doc.blocks == [Paragraph('AB')]
    assert doc.textboxes == ''


def test_active_oversize_and_later_duplicate_are_decided_at_shape_close():
    for size, limits in [(65537, {}), (64, {'max_text_chars': 2})]:
        # Enable flags after the value must still produce the active limit error.
        properties = (prop(b'gtextUNICODE', b'x'*size) + prop(b'shapeType', b'136')
                      + prop(b'fGtext', b'1') + prop(b'fGtextOK', b'1'))
        with pytest.raises(LimitExceededError, match='WordArt property'):
            parse(br'{\shp{\*\shpinst' + properties + b'}}', **limits)
        doc = parse(b'A' + shape(b'x'*size, extra=prop(b'gtextUNICODE', b'')) + b'B', **limits)
        assert doc.textboxes == '' and doc.blocks == [Paragraph('AB')]


def test_overflow_discards_scratch_and_later_shape_is_independent(monkeypatch):
    from legacy_office_parser.rtf import _WordArt
    original = _WordArt.token
    seen_overflow = False

    def checked(self, *args):
        nonlocal seen_overflow
        original(self, *args)
        assert self.size <= 65536
        if self.text_overflow and self.name == 'gtextUNICODE':
            seen_overflow = True
            assert not self.parts

    monkeypatch.setattr(_WordArt, 'token', checked)
    doc = parse(shape(b'x'*262144, extra=prop(b'fHidden', b'1')) + shape(b'Kept'))
    assert seen_overflow
    assert doc.textboxes == 'Kept'


def test_review_disabled_wordart_exact_two_character_budget_reproducer():
    source = (br'{\rtf1\ansi A' br'{\shp{\*\shpinst'
              br'{\sp{\sn shapeType}{\sv 136}}'
              br'{\sp{\sn fGtext}{\sv 0}}'
              br'{\sp{\sn fGtextOK}{\sv 1}}'
              br'{\sp{\sn gtextUNICODE}{\sv xxx}}' br'}}B}')
    doc = parse_rtf_bytes(source, Limits(max_text_chars=2))
    assert doc.text == 'AB'
    assert doc.textboxes == ''


@pytest.mark.skipif(os.environ.get('RTF_FALLBACK_LO') != '1', reason='opt-in original WordArt probe')
def test_live_explicit_wordart(tmp_path):
    sys.path.insert(0, str(ROOT/'tools'))
    try:
        from check_performance import bounded
    finally:
        sys.path.pop(0)
    source = FIXTURES/'wordart-explicit.rtf'
    result = bounded([sys.executable, str(ROOT/'tools/check_performance.py'), '--convert-child',
                      '/usr/bin/libreoffice', str(source), str(tmp_path), 'fodt'], 45)
    assert result['status'] == 'ok', result
    tree = ET.parse(tmp_path/'wordart-explicit.fodt')
    ns = {'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
          'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    assert [''.join(p.itertext()) for s in tree.findall('.//draw:custom-shape', ns)
            for p in s.findall('text:p', ns)] == ['Original WordArt']
    assert parse_rtf(source).textboxes == 'Original WordArt'
