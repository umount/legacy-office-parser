import pytest
from test_doc import fixture, parse, mutate, u32
from test_doc_textboxes import plc
from legacy_office_parser import InvalidDocumentError


def textbox_fixture(text, cps, flags, header=False):
    counts = [2, 0, 0, 0, 0, 0 if header else len(text), len(text) if header else 0]
    streams = fixture([('B\r' + text, True)], counts=counts)
    data = plc(cps, flags)
    offset = len(streams['1Table'])
    streams['1Table'] += data
    mutate(streams, 'WordDocument', 154 + (58 if header else 56) * 8,
           u32(offset) + u32(len(data)))
    return streams


@pytest.mark.parametrize('header', [False, True])
def test_reserved_textbox_range_is_excluded_from_public_result(monkeypatch, header):
    streams = textbox_fixture('LIVE\rOLD\r', [0, 5, 9], [0, 0], header)
    result = parse(monkeypatch, streams)
    assert result.textboxes == 'LIVE'
    assert 'OLD' not in result.text


def test_unbalanced_field_does_not_hide_next_textbox(monkeypatch):
    streams = textbox_fixture('A\x13bad\rNEXT\rOLD\r', [0, 6, 11, 15], [0, 0, 0])
    result = parse(monkeypatch, streams)
    assert result.textboxes == 'A\nNEXT'
    assert any('Unbalanced' in w for w in result.warnings)


def test_live_textbox_requires_paragraph_terminator(monkeypatch):
    streams = textbox_fixture('LIVE!OLD\r', [0, 5, 9], [0, 0])
    with pytest.raises(InvalidDocumentError, match='paragraph mark'):
        parse(monkeypatch, streams)
