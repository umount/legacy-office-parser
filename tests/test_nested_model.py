from dataclasses import replace

import pytest

from legacy_office_parser import Cell, Document, Limits, Paragraph, Table, LimitExceededError
from legacy_office_parser.api import _validate_result


def test_nested_structure_serializes_without_duplicate_plain_text():
    inner = Table([[Cell('inside')]])
    outer = Cell('before\ninside\nafter', blocks=[Paragraph('before'), inner, Paragraph('after')])
    doc = Document('odt', blocks=[Table([[outer]])])
    assert doc.text == 'before\ninside\nafter'
    tree = doc.to_dict()['blocks'][0]['rows'][0][0]
    assert tree['blocks'][1]['rows'][0][0]['text'] == 'inside'
    assert 'blocks' not in tree['blocks'][1]['rows'][0][0]
    assert Document('odt').to_dict()['blocks'] == []


def test_nested_cells_depth_and_retained_text_are_bounded():
    doc = Document('odt', blocks=[Table([[Cell('X', blocks=[Table([[Cell('X')]])])]])])
    _validate_result(doc, replace(Limits(), max_cells=2, max_text_chars=2, max_depth=2))
    for limits in [replace(Limits(), max_cells=1), replace(Limits(), max_text_chars=1),
                   replace(Limits(), max_depth=1)]:
        with pytest.raises(LimitExceededError):
            _validate_result(doc, limits)


def test_cycles_cannot_loop_forever_during_result_validation():
    table = Table([[Cell()]])
    table.rows[0][0].blocks.append(table)
    with pytest.raises(LimitExceededError):
        _validate_result(Document('rtf', blocks=[table]), replace(Limits(), max_depth=3))
