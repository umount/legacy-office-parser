"""Original ODT shape probes; the optional independent oracle lives in passive_research."""
import pytest

from legacy_office_parser import Limits, LimitExceededError, Paragraph, Table, parse_odt
from legacy_office_parser.api import _validate_result
from test_odf_inline_objects import package, p, frame, box, embedded, PREVIEW
from test_odf_passive_research import fixtures, package as research_package
from test_odf_stories import table, note, master, styles

KINDS = ('rect', 'ellipse', 'custom-shape')


def shape(body='', kind='rect'):
    return f'<draw:{kind}>' + body + f'</draw:{kind}>'


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('location', ['body', 'inline', 'cell', 'cell-inline', 'group', 'link', 'note', 'header'])
def test_shape_routes_once_to_detached_story(kind, location):
    value = shape(p('label'), kind)
    body = {
        'body': value, 'inline': p('A' + value + 'B'),
        'cell': table(value), 'cell-inline': table(p('A' + value + 'B')),
        'group': '<draw:g>' + value + '</draw:g>',
        'link': '<draw:a>' + value + '</draw:a>',
        'note': p(note(value)), 'header': '',
    }[location]
    extra = {'styles.xml': styles(master('<style:header>' + value + '</style:header>'))} if location == 'header' else None
    doc = parse_odt(package(body, extra))
    assert doc.textboxes == 'label'
    assert doc.text.count('label') == 1
    assert doc.story_blocks == {}
    if location.startswith('cell'):
        assert doc.blocks[0].rows[0][0].text == ('AB' if location == 'cell-inline' else '')
    if location == 'inline':
        assert doc.blocks[0].text == 'AB'


@pytest.mark.parametrize('kind', KINDS)
def test_only_direct_paragraphs_and_lists_are_shape_content(kind):
    decoys = ('<svg:title>' + p('title') + '</svg:title><svg:desc>' + p('desc') + '</svg:desc>'
              '<draw:enhanced-geometry>' + p('geometry') + '</draw:enhanced-geometry>'
              '<office:event-listeners>' + p('event') + '</office:event-listeners>'
              '<text:section>' + p('section') + '</text:section>' + table(p('table')) +
              '<text:h>heading</text:h>' + shape(p('direct nested shape')))
    doc = parse_odt(package(shape(decoys + p('first') + '<text:list><text:list-item>' +
                                  p('second') + '</text:list-item></text:list>', kind)))
    assert doc.text == 'first\n\nsecond'
    assert doc.story_blocks == {}


def test_existing_table_key_retains_shape_paragraphs_in_source_order():
    doc = parse_odt(package(shape(p('first')) + frame(box(table(p('cell')))) +
                            shape(p('last'), 'ellipse')))
    blocks = doc.story_blocks['textboxes']
    assert [type(b) for b in blocks] == [Paragraph, Table, Paragraph]
    assert doc.text == doc.textboxes == 'first\n\ncell\n\nlast'
    assert doc.to_dict()['story_blocks']['textboxes'][0]['text'] == 'first'
    _validate_result(doc, Limits())


@pytest.mark.parametrize('first', [True, False])
def test_shapes_inside_only_selected_frame_alternative(first):
    selected = box(shape(p('selected')))
    fallback = embedded(p('fallback'))
    doc = parse_odt(package(frame(PREVIEW + (selected + fallback if first else fallback + selected))))
    assert doc.textboxes == ('selected' if first else 'fallback')


def test_direct_shape_is_not_a_frame_representation():
    doc = parse_odt(package(frame(shape(p('invalid')) + box(p('valid')))))
    assert doc.text == 'valid'


def test_nested_valid_shape_is_detached_not_duplicated():
    doc = parse_odt(package(shape(p('before' + shape(p('inner'), 'ellipse') + 'after'))))
    assert doc.textboxes == 'beforeafter\n\ninner'


def test_empty_shape_and_empty_paragraph_semantics():
    assert parse_odt(package(shape() + shape(p('')))).to_dict().get('story_blocks') is None
    doc = parse_odt(package(shape() + shape(p('')) + frame(box('<table:table/>'))))
    assert doc.text == ''
    assert [type(b) for b in doc.story_blocks['textboxes']] == [Paragraph, Table]
    assert doc.story_blocks['textboxes'][0].text == ''


def test_repeated_cell_shapes_use_shared_story_projection():
    doc = parse_odt(package(table(shape(p('one')) + shape(p('two')), rows=2, columns=2)))
    assert doc.textboxes == '\n\n'.join(['one', 'two'] * 4)
    assert all(cell.text == '' for row in doc.blocks[0].rows for cell in row)
    assert doc.story_blocks == {}


def test_expanded_shape_text_exact_limit():
    data = package(shape(p('<text:s text:c="1000"/>')))
    assert len(parse_odt(data, limits=Limits(max_text_chars=1000)).textboxes) == 1000
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=999))


def test_repeated_shape_with_nested_table_story_preflights_clone(monkeypatch):
    import legacy_office_parser.odf as odf
    # Table is in a valid nested text box, never a direct shape child.
    data = package(table(shape(p(frame(box(table(table(p('<text:s text:c="1000"/>')), rows=2))))), columns=2))
    original = odf._clone_cell
    clones = []

    def clone(cell):
        if cell.blocks and not cell.text:
            clones.append(cell)
        return original(cell)

    monkeypatch.setattr(odf, '_clone_cell', clone)
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=12003))
    assert clones == []
    doc = parse_odt(data, limits=Limits(max_text_chars=12004))
    assert clones
    assert len(doc.textboxes) == 4004
    _validate_result(doc, Limits(max_text_chars=12004))


def test_original_schema_valid_reader_fixture_now_extracts_all_labels():
    kind, body = fixtures()['shapes.odt']
    doc = parse_odt(research_package(kind, body))
    assert doc.blocks[0].text == 'Host beforeHost after'
    assert doc.textboxes == '\n\n'.join(f'{kind} {part}' for kind in KINDS for part in ('paragraph', 'list'))
    assert doc.story_blocks == {}


def test_repeated_shape_paragraphs_and_legacy_are_charged_separately(monkeypatch):
    import legacy_office_parser.odf as odf
    data = package(frame(box('<table:table/>')) +
                   table(shape(p('<text:s text:c="1000"/>')), columns=2))
    original = odf._clone_cell
    clones = []

    def clone(cell):
        if cell.blocks and not cell.text:
            clones.append(cell)
        return original(cell)

    monkeypatch.setattr(odf, '_clone_cell', clone)
    with pytest.raises(LimitExceededError):
        parse_odt(data, limits=Limits(max_text_chars=4001))
    assert clones == []
    doc = parse_odt(data, limits=Limits(max_text_chars=4002))
    assert len(clones) == 1
    blocks = doc.story_blocks['textboxes']
    assert [type(b) for b in blocks] == [Table, Paragraph, Paragraph]
    assert blocks[1] is not blocks[2]
    assert len(doc.textboxes) == 2002
    _validate_result(doc, Limits(max_text_chars=4002))


def test_empty_shape_paragraph_repeat_records_preflight(monkeypatch):
    import legacy_office_parser.odf as odf

    def unexpected(cell):
        pytest.fail('empty repeated shape must be bounded before cloning')

    monkeypatch.setattr(odf, '_clone_cell', unexpected)
    with pytest.raises(LimitExceededError, match='expanded story record'):
        parse_odt(package(table(shape(p('') * 200), columns=1000)))
