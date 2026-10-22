"""Heading metadata is optional, validated everywhere, and projection-neutral."""
import json

import pytest

from legacy_office_parser import Document, Limits, Paragraph
from legacy_office_parser.api import _validate_result
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.models import Cell, Table, _clone_cell


STORIES = ('footnotes', 'endnotes', 'headers_footers', 'textboxes', 'comment_text')
LOCATIONS = ('main', 'nested', *STORIES, *(f'{story}/nested' for story in STORIES))


def document_at(location, paragraph):
    blocks = [paragraph]
    if location == 'nested' or location.endswith('/nested'):
        blocks = [Table([[Cell('text', blocks=[Table([[Cell('text', blocks=blocks)]])])]])]
    if location in ('main', 'nested'):
        return Document('doc', blocks=blocks)
    story = location.split('/')[0]
    return Document('doc', story_blocks={story: blocks}, **{story: 'text'})


@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('level', [None, *range(1, 10)])
def test_valid_heading_at_every_location(location, level):
    paragraph = Paragraph('text', heading_level=level)
    doc = document_at(location, paragraph)
    assert _validate_result(doc, Limits()) is doc
    before = doc.text
    encoded = json.dumps(doc.to_dict())
    if level is None:
        assert 'heading_level' not in encoded
    else:
        assert f'"heading_level": {level}' in encoded
    paragraph.heading_level = None
    assert doc.text == before


@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('level', [True, False, 0, -1, 10, 10**100, 1.0, '1', [], {}])
def test_invalid_heading_at_every_location(location, level):
    doc = document_at(location, Paragraph('text', heading_level=level))
    with pytest.raises(InvalidDocumentError, match='^invalid paragraph heading level$'):
        _validate_result(doc, Limits())


def test_default_json_remains_compatible():
    paragraph = Paragraph('ordinary')
    assert paragraph.heading_level is None
    assert Document('doc', blocks=[paragraph]).to_dict()['blocks'] == [
        {'text': 'ordinary', 'kind': 'paragraph'}]


def test_nested_clone_retains_heading_without_sharing():
    source = Cell('outer', blocks=[Paragraph('outer', heading_level=1), Table([
        [Cell('inner', blocks=[Paragraph('inner', heading_level=9), Paragraph('plain')])]])])
    cloned = _clone_cell(source)
    assert cloned == source and cloned is not source
    inner = cloned.blocks[1].rows[0][0].blocks
    assert inner[0].heading_level == 9
    assert inner[1].heading_level is None
    cloned.blocks[0].heading_level = 2
    inner[0].heading_level = 3
    assert source.blocks[0].heading_level == 1
    assert source.blocks[1].rows[0][0].blocks[0].heading_level == 9


@pytest.mark.parametrize('level', [None, 1, 9])
def test_heading_does_not_change_text_budget(level):
    doc = Document('doc', blocks=[Paragraph('abcd', heading_level=level)])
    assert _validate_result(doc, Limits(max_text_chars=4)).text == 'abcd'
    with pytest.raises(LimitExceededError, match='output text size limit exceeded'):
        _validate_result(doc, Limits(max_text_chars=3))


def test_heading_does_not_bypass_nested_depth_budget():
    doc = document_at('nested', Paragraph('text', heading_level=1))
    with pytest.raises(LimitExceededError, match='output table nesting depth limit exceeded'):
        _validate_result(doc, Limits(max_depth=2))
