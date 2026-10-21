"""Nested table hierarchy and expansion limits, authored XML only."""
from dataclasses import replace

import pytest

from legacy_office_parser import parse_odt, Table, Paragraph, Limits, LimitExceededError
from test_odf import package


def table(content, repeat=1, columns=1):
    return ('<table:table><table:table-row table:number-rows-repeated="%d">'
            '<table:table-cell table:number-columns-repeated="%d">%s</table:table-cell>'
            '</table:table-row></table:table>') % (repeat, columns, content)


def p(text):
    return '<text:p>' + text + '</text:p>'


def test_nested_tables_keep_interleaved_order_and_json_hierarchy():
    xml = table(p('before') + table(p('inner-before') + table(p('deep')) + p('inner-after')) + p('after'))
    doc = parse_odt(package(xml))
    cell = doc.blocks[0].rows[0][0]
    assert cell.text == 'before\ninner-before\ndeep\ninner-after\nafter'
    assert doc.text == cell.text
    assert [type(b) for b in cell.blocks] == [Paragraph, Table, Paragraph]
    child = cell.blocks[1].rows[0][0]
    assert child.blocks[1].rows[0][0].text == 'deep'
    assert doc.to_dict()['blocks'][0]['rows'][0][0]['blocks'][1]['kind'] == 'table'
    assert not doc.warnings


def test_nested_tables_in_wrappers_and_hidden_subtrees():
    xml = table('<text:section>' + p('before') + table(p('inner')) + '</text:section>' +
                '<text:section text:display="none">' + table(p('hidden')) + '</text:section>')
    doc = parse_odt(package(xml))
    assert doc.text == 'before\ninner'
    assert len(doc.blocks[0].rows[0][0].blocks) == 2


def test_repeated_nested_cells_have_independent_trees_and_cell_budget():
    xml = table(table(p('inner')), repeat=2, columns=3)
    doc = parse_odt(package(xml))
    assert doc.text.count('inner') == 6
    left, right = doc.blocks[0].rows[0][:2]
    left.blocks[0].rows[0][0].text = 'changed'
    assert right.blocks[0].rows[0][0].text == 'inner'
    # Six outer and six inner cells, including copies.
    parse_odt(package(xml), limits=replace(Limits(), max_cells=12))
    with pytest.raises(LimitExceededError):
        parse_odt(package(xml), limits=replace(Limits(), max_cells=11))


def test_nested_note_and_frame_stories_are_not_duplicated():
    note = ('<text:note text:note-class="footnote"><text:note-citation>1</text:note-citation>'
            '<text:note-body>' + p('note') + '</text:note-body></text:note>')
    box = '<draw:frame><draw:text-box>' + p('box') + '</draw:text-box></draw:frame>'
    doc = parse_odt(package(table(table(p('inner' + note + box)), repeat=2)))
    assert doc.text.count('inner') == 2
    assert doc.footnotes == 'note\n\nnote'
    assert doc.textboxes == 'box\n\nbox'
    assert 'note' not in doc.blocks[0].rows[0][0].text


def test_nested_tables_in_note_are_retained_in_its_plain_projection():
    note = ('<text:note text:note-class="endnote"><text:note-body>' +
            table(p('outer') + table(p('inner'))) + '</text:note-body></text:note>')
    doc = parse_odt(package(p('main' + note)))
    assert doc.endnotes == 'outer\ninner'
    assert doc.text == 'main\n\nouter\ninner'


def test_nested_expansion_cannot_evade_text_or_depth_limits():
    xml = table(table('<text:p><text:s text:c="2000"/></text:p>'))
    with pytest.raises(LimitExceededError):
        parse_odt(package(xml), limits=replace(Limits(), max_text_chars=3000))
    with pytest.raises(LimitExceededError):
        parse_odt(package(xml), limits=replace(Limits(), max_depth=6))
