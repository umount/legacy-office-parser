"""Encoding boundaries checked against MS-DOC, not another parser's output."""
import pytest

from test_doc import fixture, parse, mutate, u32
from legacy_office_parser import Limits, LimitExceededError


def test_all_compressed_upper_bytes_follow_fccompressed_mapping(monkeypatch):
    # MS-DOC 2.9.73: unlike Windows-1252, 80/8E/9E keep their numeric values.
    special = {
        0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E, 0x85: 0x2026,
        0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6, 0x89: 0x2030,
        0x8A: 0x0160, 0x8B: 0x2039, 0x8C: 0x0152,
        0x91: 0x2018, 0x92: 0x2019, 0x93: 0x201C, 0x94: 0x201D,
        0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014, 0x98: 0x02DC,
        0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153,
        0x9F: 0x0178,
    }
    result = parse(monkeypatch, fixture([(bytes(range(32, 256)) + b'\r', True)]))
    assert result.blocks[0].text == ''.join(chr(special.get(i, i)) for i in range(32, 256))


def test_multilingual_text_survives_every_utf16_piece_boundary(monkeypatch):
    text = 'Ёж Ελληνικά العربية עברית 中文 日本語 한글 e\u0301 😀 𐐀'
    raw = (text + '\r').encode('utf-16le')
    for boundary in range(2, len(raw), 2):
        result = parse(monkeypatch, fixture([(raw[:boundary], False), (raw[boundary:], False)]))
        assert result.blocks[0].text == text
        assert not any('UTF-16' in w for w in result.warnings)


@pytest.mark.parametrize('raw,expected', [
    (b'\x00\xd8x\x00\r\x00', '\ufffdx'),
    (b'\x00\xdc\r\x00', '\ufffd'),
    (b'\x00\xd8\x00\xd8\r\x00', '\ufffd\ufffd'),
])
def test_unpaired_utf16_units_are_explicitly_replaced(monkeypatch, raw, expected):
    result = parse(monkeypatch, fixture([(raw, False)]))
    assert result.blocks[0].text == expected
    assert any('UTF-16' in w for w in result.warnings)


def test_character_limit_counts_utf16_units_including_surrogate_pairs(monkeypatch):
    streams = fixture([('😀\r', False)])
    assert parse(monkeypatch, streams, Limits(max_text_chars=3)).blocks[0].text == '😀'
    with pytest.raises(LimitExceededError):
        parse(monkeypatch, streams, Limits(max_text_chars=2))


def test_fccompressed_reserved_high_bit_is_ignored(monkeypatch):
    streams = fixture([('text\r', True)])
    # One piece: CLX header + two CPs + PCD flags = fc field offset 15.
    mutate(streams, '1Table', 15, u32(0xC0000800))
    assert parse(monkeypatch, streams).blocks[0].text == 'text'
