"""Auxiliary DOC table structure is separate from the body and its projection."""
import pytest

from legacy_office_parser.api import _validate_result
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Cell, Document, Paragraph, Table
from test_doc import IN, ROW, definition, fixture, parse, sprm, u32


@pytest.mark.parametrize('index,attr', [(1, 'footnotes'), (2, 'headers_footers'),
                                      (4, 'endnotes'), (5, 'textboxes'), (6, 'textboxes')])
def test_story_nested_table(monkeypatch, index, attr):
    inner = IN + sprm(0x6649, u32(2))
    cell = inner + sprm(0x244B, 1)
    row = inner + sprm(0x244C, 1) + definition([0, 0])
    story = 'before\ra\rb\r\rafter\7\7'
    counts = [0] * 7
    counts[0], counts[index] = 5, len(story)
    streams = fixture([('body\r' + story, True)], counts=counts,
                      props=[b'', IN, cell, cell, row, IN, ROW + definition([0])])
    out = parse(monkeypatch, streams)
    assert out.blocks == [Paragraph('body')]
    assert getattr(out, attr) == 'before\na\tb\nafter'
    outer = out.story_blocks[attr][0].rows[0][0]
    assert outer.blocks[0] == Paragraph('before')
    assert [c.text for c in outer.blocks[1].rows[0]] == ['a', 'b']
    assert outer.blocks[2] == Paragraph('after')
    assert out.text.count('before') == 1
    assert out.to_dict()['story_blocks'][attr][0]['rows'][0][0]['blocks'][1]['kind'] == 'table'


def test_plain_story_keeps_json_contract(monkeypatch):
    out = parse(monkeypatch, fixture([('body\rnote\r', True)], counts=[5, 5, 0, 0, 0, 0, 0]))
    assert out.footnotes == 'note'
    assert not out.story_blocks
    assert 'story_blocks' not in out.to_dict()


def test_auxiliary_projection_counted_in_text_budget(monkeypatch):
    # Raw CP count is 15. Retained tree and its string contain 20 characters.
    streams = fixture([('main\rabcdefgh\7\7', True)], counts=[5, 10, 0, 0, 0, 0, 0],
                      props=[b'', IN, ROW])
    with pytest.raises(LimitExceededError, match='text'):
        parse(monkeypatch, streams, Limits(max_text_chars=19))
    out = parse(monkeypatch, streams, Limits(max_text_chars=20))
    assert out.footnotes == 'abcdefgh'
    _validate_result(out, Limits(max_text_chars=20))


def test_auxiliary_structure_validated_by_public_api():
    out = Document('doc', footnotes='abc', story_blocks={
        'footnotes': [Table([[Cell('abc')]])]})
    with pytest.raises(LimitExceededError, match='text'):
        _validate_result(out, Limits(max_text_chars=5))
    out.story_blocks['footnotes'][0].rows.append([Cell('')])
    with pytest.raises(LimitExceededError, match='cell'):
        _validate_result(out, Limits(max_cells=1))
