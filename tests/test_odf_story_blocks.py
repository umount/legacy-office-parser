"""Authored tiny ODT packages; no private documents or generated expectations."""
from dataclasses import replace

import pytest

from legacy_office_parser.models import Note, NoteBodyRange
from legacy_office_parser import Limits, LimitExceededError, Paragraph, Table, parse_odt
from legacy_office_parser.api import _validate_result
from legacy_office_parser.odf import parse_odf_bytes
from test_odf import package
from test_odf_stories import frame, master, note, styles, table


def p(text=''):
    return '<text:p>' + text + '</text:p>'


def document(key, contents):
    if key == 'headers_footers':
        headers = ''.join(f'<style:{tag}>{body}</style:{tag}>' for tag, body in
                          zip(('header', 'footer', 'header-left'), contents))
        return package('', extra={'styles.xml': styles(master(headers))})
    if key == 'textboxes':
        return package(''.join(frame(body) for body in contents))
    return package(p(''.join(note(body, key[:-1]) for body in contents)))


KEYS = ['footnotes', 'endnotes', 'headers_footers', 'textboxes']


@pytest.mark.parametrize('key', KEYS)
def test_table_key_keeps_all_sinks_and_interleaved_blocks(key):
    data = document(key, [p('first'), p('before') + table(p('cell')) + p('after'), p('last')])
    doc = parse_odt(data)
    assert list(doc.story_blocks) == [key]
    blocks = doc.story_blocks[key]
    assert [type(b) for b in blocks] == [Paragraph, Paragraph, Table, Paragraph, Paragraph]
    assert [b.text for b in blocks if isinstance(b, Paragraph)] == ['first', 'before', 'after', 'last']
    assert blocks[2].rows[0][0].text == 'cell'
    expected = 'first\n\nbefore\n\ncell\n\nafter\n\nlast'
    assert getattr(doc, key) == doc.text == expected
    assert doc.to_dict()['story_blocks'][key][2]['rows'][0][0]['text'] == 'cell'
    assert doc.text.count('cell') == 1


@pytest.mark.parametrize('key', KEYS)
def test_pure_text_notes_keep_boundaries_and_absent_stories_stay_absent(key):
    doc = parse_odt(document(key, ['', p(''), p('text')]))
    assert getattr(doc, key) == doc.text == 'text'
    if key in ('footnotes', 'endnotes'):
        # First block is an empty-body marker; second is a source paragraph.
        assert doc.story_blocks == {key: [Paragraph(''), Paragraph(''), Paragraph('text')]}
        assert doc.notes == [Note(key[:-1], 1, NoteBodyRange(key, 0, 1)),
                             Note(key[:-1], 2, NoteBodyRange(key, 1, 2)),
                             Note(key[:-1], 3, NoteBodyRange(key, 2, 3))]
        assert doc.to_dict()['story_blocks'] == {key: [
            {'kind': 'paragraph', 'text': ''}, {'kind': 'paragraph', 'text': ''},
            {'kind': 'paragraph', 'text': 'text'}]}
    else:
        assert doc.story_blocks == {}
        assert doc.notes == []
        assert 'story_blocks' not in doc.to_dict()
    absent = parse_odt(package(''))
    assert absent.notes == []
    assert 'story_blocks' not in absent.to_dict()


@pytest.mark.parametrize('key', KEYS)
def test_zero_row_zero_cell_and_empty_paragraph_semantics(key):
    zero_rows = '<table:table/>'
    zero_cells = '<table:table><table:table-row/></table:table>'
    doc = parse_odt(document(key, ['', p('') + zero_rows, zero_cells + p('')]))
    blocks = doc.story_blocks[key]
    if key in ('footnotes', 'endnotes'):
        # Empty first body needs a marker; source empty paragraphs remain distinct.
        assert blocks == [Paragraph(''), Paragraph(''), Table([]), Table([[]]), Paragraph('')]
        assert doc.notes == [Note(key[:-1], 1, NoteBodyRange(key, 0, 1)),
                             Note(key[:-1], 2, NoteBodyRange(key, 1, 3)),
                             Note(key[:-1], 3, NoteBodyRange(key, 3, 5))]
    else:
        assert blocks == [Paragraph(''), Table([]), Table([[]]), Paragraph('')]
        assert doc.notes == []
    assert getattr(doc, key) == doc.text == ''


@pytest.mark.parametrize('key', KEYS)
def test_nested_tables_keep_structure_and_projection(key):
    content = table(p('outer-before') + table(p('inner')) + p('outer-after'))
    doc = parse_odt(document(key, [content]))
    cell = doc.story_blocks[key][0].rows[0][0]
    assert [type(b) for b in cell.blocks] == [Paragraph, Table, Paragraph]
    assert cell.blocks[1].rows[0][0].text == 'inner'
    assert cell.text == getattr(doc, key) == doc.text == 'outer-before\ninner\nouter-after'
    assert doc.to_dict()['story_blocks'][key][0]['rows'][0][0]['blocks'][1]['kind'] == 'table'


def test_nested_same_key_reserves_outer_encounter_order():
    doc = parse_odt(package(frame(p('before') + frame(table(p('inner'))) + p('after')) +
                            frame('') + frame(frame(p('last')))))
    assert [type(b) for b in doc.story_blocks['textboxes']] == [Paragraph, Paragraph, Table, Paragraph]
    assert doc.textboxes == doc.text == 'before\n\nafter\n\ninner\n\nlast'


def test_nested_detached_stories_are_never_folded_into_parent():
    body = table(p('header' + frame(table(p('box'))) + note(table(p('foot')))))
    doc = parse_odt(document('headers_footers', [body]))
    assert set(doc.story_blocks) == {'headers_footers', 'textboxes', 'footnotes'}
    for key, value in [('headers_footers', 'header'), ('textboxes', 'box'), ('footnotes', 'foot')]:
        assert doc.story_blocks[key][0].rows[0][0].text == getattr(doc, key) == value
        assert doc.text.count(value) == 1


@pytest.mark.parametrize('kind', ['footnote', 'endnote', 'textboxes'])
def test_repeated_stories_keep_row_major_order_and_independent_trees(kind):
    wrap = frame if kind == 'textboxes' else lambda body: note(body, kind)
    first = wrap(p('A') + table(p('B') + table(p('C'))))
    second = wrap(table(p('D')))
    data = package(table(p(first + second), rows=2, columns=3))
    doc = parse_odt(data, limits=Limits(max_cells=24))
    key = kind if kind == 'textboxes' else kind + 's'
    blocks = doc.story_blocks[key]
    assert len(blocks) == 18
    assert getattr(doc, key) == '\n\n'.join(['A\n\nB\nC\n\nD'] * 6)
    for index in range(0, 18, 3):
        assert blocks[index].text == 'A'
        assert blocks[index + 1].rows[0][0].blocks[1].rows[0][0].text == 'C'
        assert blocks[index + 2].rows[0][0].text == 'D'
    blocks[0].text = 'changed'
    blocks[1].rows[0][0].blocks[1].rows[0][0].text = 'changed'
    assert blocks[3].text == 'A'
    assert blocks[4].rows[0][0].blocks[1].rows[0][0].text == 'C'
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_cells=23))


@pytest.mark.parametrize('key', KEYS)
def test_retained_structure_and_legacy_projection_have_separate_text_budgets(key):
    # Small XML, large expanded display text: source XML cannot mask this check.
    data = document(key, [table(p('<text:s text:c="1000"/>'))])
    for parse in (parse_odt, lambda data, limits: parse_odf_bytes(data, limits)):
        doc = parse(data, limits=Limits(max_text_chars=2000))
        assert len(doc.text) == 1000
        with pytest.raises(LimitExceededError, match='output text size'):
            parse(data, limits=Limits(max_text_chars=1999))


def test_repeated_nested_structure_counts_every_projection():
    data = document('textboxes', [table(table(p('<text:s text:c="1000"/>')), rows=2)])
    # Two outer projections + two inner cells + legacy string and row separator.
    doc = parse_odt(data, limits=Limits(max_text_chars=6001, max_cells=4))
    assert len(doc.textboxes) == 2001
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=6000))
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_cells=3))
    with pytest.raises(LimitExceededError, match='output table nesting'):
        _validate_result(doc, replace(Limits(), max_depth=1))
    with pytest.raises(LimitExceededError, match='XML depth'):
        parse_odt(data, limits=Limits(max_depth=6))


def test_tables_and_note_bodies_are_retained_but_hidden_tables_do_not_opt_in():
    body = (frame(table(p('box'))) + p(note(p('foot'))) +
            frame('<text:section text:display="none">' + table(p('hidden')) + '</text:section>'))
    doc = parse_odt(package(body))
    assert set(doc.story_blocks) == {'textboxes', 'footnotes'}
    assert doc.story_blocks['footnotes'] == [Paragraph('foot')]
    assert doc.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert doc.footnotes == 'foot'
    assert doc.text == 'foot\n\nbox'
    hidden_only = document('textboxes', [p('visible') + '<text:section text:display="none">' +
                                       table(p('hidden')) + '</text:section>'])
    assert parse_odt(hidden_only).story_blocks == {}


def test_repeated_empty_structure_is_bounded_before_cloning(monkeypatch):
    import legacy_office_parser.odf as odf

    def unexpected_clone(cell):
        pytest.fail('excess empty story copies must be rejected before allocation')

    data = package(table(frame(p('') * 200 + '<table:table/>'), columns=1000))
    monkeypatch.setattr(odf, '_clone_cell', unexpected_clone)
    with pytest.raises(LimitExceededError, match='expanded story record'):
        parse_odt(data)


def test_repeated_empty_story_tables_survive_without_separators():
    data = package(table(frame(p('') + '<table:table/>'), rows=2, columns=3))
    doc = parse_odt(data)
    assert doc.textboxes == ''
    blocks = doc.story_blocks['textboxes']
    assert [type(b) for b in blocks] == [Paragraph, Table] * 6
    blocks[1].rows.append([])
    assert blocks[3].rows == []


@pytest.mark.parametrize('repeat_args', [{'columns': 2}, {'rows': 2}])
def test_repeated_descendant_text_is_preflighted_before_story_clone(monkeypatch, repeat_args):
    import legacy_office_parser.odf as odf

    data = package(table(frame(table(table(p('<text:s text:c="1000"/>')))), **repeat_args))
    original_clone = odf._clone_cell
    story_clones = []

    def checked_clone(cell):
        # Ordinary table-cell construction is necessary to parse the template.
        # repeat_stories wraps the detached blocks in a cell with no projection.
        if cell.blocks and not cell.text:
            story_clones.append(cell)
        return original_clone(cell)

    monkeypatch.setattr(odf, '_clone_cell', checked_clone)
    for maximum in (4000, 6001):
        with pytest.raises(LimitExceededError, match='retained story text'):
            parse_odt(data, limits=Limits(max_text_chars=maximum))
        assert not story_clones
    doc = parse_odt(data, limits=Limits(max_text_chars=6002))
    assert len(story_clones) == 1
    assert len(doc.textboxes) == 2002
    assert len(doc.story_blocks['textboxes']) == 2


def test_all_story_kinds_preflight_before_any_story_clone(monkeypatch):
    import legacy_office_parser.odf as odf

    content = table(table(p('<text:s text:c="1000"/>')))
    data = package(table(p(note(table(p('small'))) + frame(content)), columns=2))
    original_clone = odf._clone_cell

    def checked_clone(cell):
        if cell.blocks and not cell.text:
            pytest.fail('no story kind may clone before the combined text check')
        return original_clone(cell)

    monkeypatch.setattr(odf, '_clone_cell', checked_clone)
    with pytest.raises(LimitExceededError, match='retained story text'):
        parse_odt(data, limits=Limits(max_text_chars=4000))


def test_preflight_includes_earlier_text_sinks_when_key_gains_table(monkeypatch):
    import legacy_office_parser.odf as odf

    # Earlier pure-text copies become structured when a later sink has a table.
    data = package(table(frame(p('<text:s text:c="1000"/>')), columns=2) +
                   table(frame(table(p('x'))), columns=2))
    original_clone = odf._clone_cell
    cloned_paragraphs = []

    def checked_clone(cell):
        if cell.blocks and not cell.text:
            assert isinstance(cell.blocks[0], Paragraph), 'table story must fail before cloning'
            cloned_paragraphs.append(cell)
        return original_clone(cell)

    monkeypatch.setattr(odf, '_clone_cell', checked_clone)
    with pytest.raises(LimitExceededError, match='retained story text'):
        parse_odt(data, limits=Limits(max_text_chars=4009))
    assert len(cloned_paragraphs) == 1
    monkeypatch.setattr(odf, '_clone_cell', original_clone)
    assert len(parse_odt(data, limits=Limits(max_text_chars=4010)).textboxes) == 2008


def test_column_then_row_story_copies_do_not_double_charge_structure():
    data = package(table(frame(table(table(p('<text:s text:c="1000"/>')))), rows=2, columns=2))
    # Four legacy projections with three separators, plus eight cell projections.
    doc = parse_odt(data, limits=Limits(max_text_chars=12006))
    assert len(doc.textboxes) == 4006
    assert len(doc.story_blocks['textboxes']) == 4
    with pytest.raises(LimitExceededError, match='retained story text'):
        parse_odt(data, limits=Limits(max_text_chars=12005))


@pytest.mark.parametrize('inner_repeat', [{'rows': 2}, {'columns': 2}])
def test_original_story_descendant_copies_are_charged_before_detached_clone(monkeypatch, inner_repeat):
    import legacy_office_parser.odf as odf

    data = package(table(frame(table(table(p('<text:s text:c="1000"/>')), **inner_repeat)),
                         columns=2))
    original_clone = odf._clone_cell
    detached_clones = []

    def checked_clone(cell):
        if cell.blocks and not cell.text:
            detached_clones.append(cell)
        return original_clone(cell)

    monkeypatch.setattr(odf, '_clone_cell', checked_clone)
    for maximum in (11004, 12003):
        with pytest.raises(LimitExceededError, match='retained story text'):
            parse_odt(data, limits=Limits(max_text_chars=maximum))
        assert detached_clones == []
    doc = parse_odt(data, limits=Limits(max_text_chars=12004))
    assert len(detached_clones) == 1
    assert len(doc.textboxes) == 4004
    assert len(doc.story_blocks['textboxes']) == 2


@pytest.mark.parametrize('outer_copies,maximum', [(1, 12011), (2, 24024)])
def test_completed_story_charge_excludes_nested_same_key_and_its_copies(outer_copies, maximum):
    inner = frame(table(table(p('<text:s text:c="1000"/>')), rows=2))
    outer = frame(table(p('a' + inner), rows=2))
    data = package(table(outer, columns=outer_copies))
    # One outer story: two 'a' cell projections + two nested stories, each
    # retaining 4000 chars. Its pooled legacy text is 4009 chars. A second
    # occurrence adds another 12011 chars plus a two-character separator.
    doc = parse_odt(data, limits=Limits(max_text_chars=maximum))
    assert len(doc.textboxes) == 4009 * outer_copies + 2 * (outer_copies - 1)
    assert len(doc.story_blocks['textboxes']) == 3 * outer_copies
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=maximum - 1))


def test_completed_story_charge_excludes_nested_other_key_and_its_copies():
    inner = note(table(table(p('<text:s text:c="1000"/>')), rows=2))
    data = package(frame(table(p('a' + inner), rows=2)))
    # Same retained trees as above, but separate legacy fields omit the
    # inter-key separator from _validate_result's allocation accounting.
    doc = parse_odt(data, limits=Limits(max_text_chars=12009))
    assert doc.textboxes == 'a\na'
    assert len(doc.footnotes) == 4004
    assert set(doc.story_blocks) == {'footnotes', 'textboxes'}
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=12008))
