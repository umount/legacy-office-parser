"""Independent literal Unicode/ownership expectations; no author test helpers."""
import pytest

from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.rtf import parse_rtf_bytes


def artwork(value, extra=b''):
    return (br'{\shp{\*\shpinst'
            br'{\sp{\sn shapeType}{\sv 136}}'
            br'{\sp{\sn fGtext}{\sv 1}}'
            br'{\sp{\sn fGtextOK}{\sv 1}}'
            br'{\sp{\sn gtextUNICODE}{\sv ' + value + b'}}' + extra + b'}}')


def read(body, header=b'', **limits):
    return parse_rtf_bytes(br'{\rtf1\ansi ' + header + body + b'}', Limits(**limits))


@pytest.mark.parametrize('value,expected', [
    (br'\u1040?Z', 'АZ'),
    (br'\uc2\u1040\'c0?Z', 'АZ'),
    (br'\uc0\u1040Z', 'АZ'),
    (br'\u1040\{Z', 'АZ'),
    (br'\u1040\ansicpg37 Z', 'АZ'),
    (br'\u1040\uc0 Z\u1041?Q', 'АZБQ'),
    (br'\u1040\bin3 {}xZ', 'АZ'),
    (br'\u-10179?\u-8704?', '😀'),
    (br'\uc0\u-10179\u-8704', '😀'),
    (br'\u-3?', '\ufffd'),
])
def test_review_fallback_units_and_signed_unicode(value, expected):
    assert read(artwork(value)).textboxes == expected


@pytest.mark.parametrize('value', [
    br'\u-10179?', br'\u-8704?', br'\u-8704?\u-10179?',
    br'\u-10179?X\u-8704?', br'\u-10179?\u65?',
    br'\u65536?', br'\u-32769?', br'\u0?', br'\u127?',
    br'\u159?', br'\uc-1\u65?', br'\u65?{\header Escape}',
])
def test_review_invalid_value_never_publishes_prefix(value):
    doc = read(b'A' + artwork(b'Prefix' + value) + b'B')
    assert doc.text == 'AB'
    assert doc.textboxes == doc.headers_footers == ''


@pytest.mark.parametrize('header,value,expected', [
    (br'\ansicpg1252 ', br'\'e9', 'é'),
    (br'\ansicpg1251 ', br'\'c0', 'А'),
    (br'\ansicpg932 ', br'\'82\'a0', 'あ'),
    (br'\ansicpg932 ', b'\x82' + br"\'a0", 'あ'),
    (br'\deff0{\fonttbl{\f0\fcharset204 Cyrillic;}}', br'\'c0', 'А'),
    (br'\deff0{\fonttbl{\f0\fcharset204\cpg1252 Latin;}}', br'\'e9', 'é'),
])
def test_review_encoding_is_inherited_and_token_independent(header, value, expected):
    assert read(artwork(value), header).textboxes == expected


def test_review_property_uc_does_not_change_body_or_next_shape():
    doc = read(artwork(br'\uc0\u1040') + br'\u1041?'
               + artwork(br'\u1042?'))
    assert doc.blocks[0].text == 'Б'
    assert doc.textboxes == 'А\nВ'
    assert read(artwork(br'\u1040??Z'), br'\uc2 ').textboxes == 'АZ'


def test_review_surrogates_never_join_between_shapes():
    doc = read(artwork(br'\u-10179?') + artwork(br'\u-8704?')
               + artwork(br'\u1040?'))
    assert doc.textboxes == 'А'


@pytest.mark.parametrize('ancestor', [
    br'\fldinst', br'\object', br'\shprslt', br'\*\unknown',
    br'\v', br'\deleted', br'\shpgrp', br'\*\do',
])
def test_review_suppressed_unicode_does_not_escape(ancestor):
    doc = read(b'A{' + ancestor + artwork(br'\uc0\u1040') + b'}B')
    assert doc.text == 'AB'


def test_review_inactive_unicode_alternate_is_not_observed():
    doc = read(br'{\upr{' + artwork(br'\u1040?') + br'}{\*\ud '
               + artwork(br'\u1041?') + b'}}')
    assert doc.textboxes == 'Б'


def test_review_decoded_budget_counts_astral_character_once():
    assert read(artwork(br'\u-10179?\u-8704?'), max_text_chars=1).textboxes == '😀'
    with pytest.raises(LimitExceededError):
        read(artwork(br'\u-10179?\u-8704?X'), max_text_chars=1)


@pytest.mark.parametrize('tail', [
    br'{\sp{\sn fHidden}{\sv 1}}',
    br'{\sp{\sn unknown}{\sv 1}}',
    br'{\sp{\sn gtextUNICODE}{\sv Duplicate}}',
])
def test_review_overflow_and_late_disqualification(tail):
    doc = read(b'A' + artwork(br'\u1040?' * 1000, tail) + b'B', max_text_chars=2)
    assert doc.text == 'AB'


@pytest.mark.parametrize('tail', [br'\u-10179?', br'\'81', br'\u127?'])
def test_review_overflow_keeps_validating_decoded_tail(tail):
    doc = read(b'A' + artwork(br'\u1040?' * 1000 + tail) + b'B', max_text_chars=2)
    assert doc.text == 'AB'


def test_review_large_unicode_reaches_deferred_eligibility():
    with pytest.raises(LimitExceededError, match='WordArt property text'):
        read(artwork(br'\u1040?' * 100000), max_text_chars=128, max_records=300000)
