"""Literal MS-DOC outline oracles: fixed styles, inherited/direct PAPX and stories."""
import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits
from legacy_office_parser.errors import UnsupportedFormatError
from legacy_office_parser.models import Paragraph
from test_doc import fixture, parse, sprm, u16
from test_doc_styles import style, stylesheet, pap_style
from test_doc_nested import streams, cell, row, paragraph
from test_doc_comments import build


def outline(value):
    return sprm(0x2640, value)


def records(*custom):
    # Actual fixed-index application IDs; arbitrary names never drive headings.
    fixed = []
    for index in range(10):
        raw = bytearray(style(index))
        raw[2:4] = u16(index)
        fixed.append(bytes(raw))
    return fixed + [b'\0\0'] * 5 + list(custom)


def source(*, selected=0, direct=b'', styles=None, text='Title\r', prms=None, prcs=()):
    data = fixture([(text, False)], props=[direct], prms=prms, prcs=prcs)
    stylesheet(data, records() if styles is None else styles)
    pap_style(data, selected)
    return data


@pytest.mark.parametrize('level', range(1, 10))
@pytest.mark.parametrize('direct', [b'', outline(0), outline(9)])
def test_fixed_headings_ignore_direct_outline(monkeypatch, level, direct):
    result = parse(monkeypatch, source(selected=level, direct=direct))
    assert result.blocks == [Paragraph('Title', heading_level=level)]
    assert result.text == 'Title'


@pytest.mark.parametrize('value', range(10))
def test_direct_outline_values(monkeypatch, value):
    result = parse(monkeypatch, source(direct=outline(value)))
    assert result.blocks[0].heading_level == (value + 1 if value < 9 else None)


@pytest.mark.parametrize('local,direct,expected', [
    (b'', b'', 3), (outline(4), b'', 5), (outline(9), b'', None),
    (b'', outline(9), None), (outline(9), outline(0), 1),
])
def test_custom_inheritance_and_body_override(monkeypatch, local, direct, expected):
    data = source(selected=16, direct=direct,
                  styles=records(style(15, papx=outline(2)), style(16, base=15, papx=local)))
    assert parse(monkeypatch, data).blocks[0].heading_level == expected


def test_custom_child_of_fixed_heading_can_override(monkeypatch):
    data = source(selected=15, styles=records(style(15, base=2, papx=outline(9))))
    assert parse(monkeypatch, data).blocks[0].heading_level is None
    data = source(selected=15, styles=records(style(15, base=2)))
    # No stored POutLvl is inherited merely from the parent's fixed index.
    assert parse(monkeypatch, data).blocks[0].heading_level is None


@pytest.mark.parametrize('operations,expected', [
    (outline(3) + sprm(0x4600, u16(0)), None),
    (outline(3) + sprm(0x4600, u16(15)), 6),
    (sprm(0x4600, u16(15)) + outline(9), None),
    (outline(9) + sprm(0x4600, u16(2)), 2),
    (sprm(0x4600, u16(2)) + outline(9), 2),
    (sprm(0x4600, u16(200)) + sprm(0x4600, u16(0)), None),
])
def test_style_change_resets_outline_in_order(monkeypatch, operations, expected):
    data = source(direct=operations, styles=records(style(15, papx=outline(5))))
    assert parse(monkeypatch, data).blocks[0].heading_level == expected


@pytest.mark.parametrize('selected,value,expected', [(0, 0, 1), (0, 8, 9), (0, 9, None), (3, 9, 3)])
def test_compact_outline_overrides_papx(monkeypatch, selected, value, expected):
    data = source(selected=selected, direct=outline(2), prms=[(0x78 << 1) | (value << 8)])
    result = parse(monkeypatch, data)
    assert result.blocks[0].heading_level == expected
    assert not any('compact piece formatting' in w for w in result.warnings)


def test_complex_prm_and_direct_last_wins(monkeypatch):
    data = source(direct=outline(1), prms=[1], prcs=[outline(5) + outline(8)])
    assert parse(monkeypatch, data).blocks[0].heading_level == 9


@pytest.mark.parametrize('where', ['direct', 'style', 'compact'])
@pytest.mark.parametrize('value', [10, 255])
def test_invalid_outline_is_bounded_error(monkeypatch, where, value):
    kwargs = ({'direct': outline(value)} if where == 'direct' else
              {'styles': records(style(15, papx=outline(value)))} if where == 'style' else
              {'prms': [(0x78 << 1) | (value << 8)]})
    with pytest.raises(InvalidDocumentError, match='outline'):
        parse(monkeypatch, source(**kwargs))


@pytest.mark.parametrize('styles', [
    records(style(15, base=16), style(16, base=15)),
    records(style(15, base=200)),
    records(style(15, base=16), style(16, kind=2)),
    records(style(15, base=14)),
])
def test_bad_outline_inheritance_graph(monkeypatch, styles):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, source(selected=15, styles=styles))


def test_outline_inheritance_depth_budget(monkeypatch):
    with pytest.raises(LimitExceededError, match='inheritance depth'):
        parse(monkeypatch, source(selected=16, styles=records(style(15), style(16, base=15))),
              Limits(max_depth=1))


@pytest.mark.parametrize('text', ['\r', ' \t\r'])
def test_empty_headings_do_not_create_breadcrumbs(monkeypatch, text):
    assert parse(monkeypatch, source(selected=1, text=text)).blocks[0].heading_level is None


def test_hidden_heading_has_no_output_level(monkeypatch):
    styles = records()
    styles[1] = style(1, chpx=sprm(0x083C, 1))
    assert parse(monkeypatch, source(selected=1, styles=styles)).blocks == [Paragraph('')]


def test_no_style_name_guess_or_list_level_guess(monkeypatch):
    data = source(selected=15, styles=records(style(15)), direct=sprm(0x260A, 1))
    assert parse(monkeypatch, data).blocks[0].heading_level is None


def test_table_headings_preserve_paragraphs_and_text(monkeypatch):
    data = streams(paragraph(1, 'Heading'), cell(1, 'Body'), row(1))
    stylesheet(data, records())
    pap_style(data, 2, paragraph=0)
    result = parse(monkeypatch, data)
    target = result.blocks[0].rows[0][0]
    assert target.text == 'Heading\nBody'
    assert target.blocks == [Paragraph('Heading', 2), Paragraph('Body')]
    assert result.text == 'Heading\nBody'


def test_nested_heading_stays_in_source_cell(monkeypatch):
    data = streams(paragraph(1, 'Outer'), cell(2, 'Inner'), row(2), cell(1, 'Tail'), row(1))
    stylesheet(data, records())
    pap_style(data, 3, paragraph=1)
    result = parse(monkeypatch, data)
    outer = result.blocks[0].rows[0][0]
    inner = outer.blocks[1].rows[0][0]
    assert inner.blocks == [Paragraph('Inner', 3)]
    assert outer.blocks[0] == Paragraph('Outer')
    assert result.text == 'Outer\nInner\nTail'


def test_comment_body_heading_preserves_owner_and_single_projection(monkeypatch):
    data = build()
    stylesheet(data, records())
    pap_style(data, 2, paragraph=1)
    result = parse(monkeypatch, data)
    assert result.story_blocks['comment_text'] == [Paragraph('Body', 2)]
    assert result.comment_text == 'Body' and result.text.count('Body') == 1
    assert result.comments[0].body.block_start == 0


@pytest.mark.parametrize('group,prms', [(sprm(0x2602, 1), None), (b'', [(0x04 << 1) | (1 << 8)])])
def test_style_increment_remains_explicitly_unsupported(monkeypatch, group, prms):
    with pytest.raises(UnsupportedFormatError, match='increment'):
        parse(monkeypatch, source(direct=group, prms=prms))


@pytest.mark.parametrize('index,attr', [(1, 'footnotes'), (2, 'headers_footers'),
                                      (4, 'endnotes'), (5, 'textboxes'), (6, 'textboxes')])
def test_auxiliary_story_retains_heading_blocks(monkeypatch, index, attr):
    counts = [5, 0, 0, 0, 0, 0, 0]
    counts[index] = 6
    data = fixture([('Main\rStory\r', False)], counts=counts, props=[b'', outline(3)])
    result = parse(monkeypatch, data)
    assert result.blocks == [Paragraph('Main')]
    assert result.story_blocks[attr] == [Paragraph('Story', 4)]
    assert getattr(result, attr) == 'Story'
    assert result.text == 'Main\n\nStory'


def test_cell_heading_retained_text_is_budgeted(monkeypatch):
    data = streams(cell(1, 'Long title'), row(1))
    stylesheet(data, records())
    pap_style(data, 1)
    with pytest.raises(LimitExceededError, match='output text'):
        parse(monkeypatch, data, Limits(max_text_chars=15))


def test_heading_does_not_move_comment_anchor(monkeypatch):
    from test_doc import IN, ROW, definition
    data = build('Title\x05\7\7', props=[IN + outline(1), ROW + definition([0]), b'', b''])
    result = parse(monkeypatch, data)
    assert result.blocks[0].rows[0][0].blocks == [Paragraph('Title', 2)]
    assert result.comments[0].anchor_path == ['blocks', 0, 'rows', 0, 0, 'blocks', 0]
    assert result.comment_text == 'Body'


@pytest.mark.parametrize('name', ['Heading 1', 'Заголовок 1', 'Überschrift 1'])
def test_localized_or_english_names_are_not_heading_evidence(monkeypatch, name):
    old = style(15)
    # Replace just the counted UTF-16 style name in this original style record.
    raw = old[2:12] + u16(len(name)) + (name + '\0').encode('utf-16le') + old[18:]
    named = u16(len(raw)) + raw
    assert parse(monkeypatch, source(selected=15, styles=records(named))).blocks == [Paragraph('Title')]


def test_huge_papx_outline_and_later_piece_body_override(monkeypatch):
    from test_doc import u32
    group = outline(1) + sprm(0x4600, u16(0)) + outline(7)
    data = source(direct=sprm(0x6646, u32(0)))
    data['Data'] = u16(len(group)) + group
    assert parse(monkeypatch, data).blocks == [Paragraph('Title', 8)]
    data = source(direct=sprm(0x6646, u32(0)), prms=[(0x78 << 1) | (9 << 8)])
    data['Data'] = u16(len(group)) + group
    assert parse(monkeypatch, data).blocks == [Paragraph('Title')]


def test_increment_is_forbidden_in_style_upx(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='forbidden'):
        parse(monkeypatch, source(styles=records(style(15, papx=sprm(0x2602, 1)))))


@pytest.mark.parametrize('base_operand,expected', [
    (b'', None), (outline(1), 2), (outline(9), None), (outline(4), 5),
])
@pytest.mark.parametrize('selected', [2, 15, 16])
def test_fixed_ancestor_raw_outline_only_applies_to_custom_descendants(monkeypatch, base_operand, expected, selected):
    definitions = records(style(15, base=2), style(16, base=15))
    definitions[2] = style(2, papx=base_operand)
    result = parse(monkeypatch, source(selected=selected, styles=definitions))
    assert result.blocks == [Paragraph('Title', 2 if selected == 2 else expected)]


def test_fixed_ancestor_without_operand_preserves_earlier_inherited_operand(monkeypatch):
    definitions = records(style(15, base=2))
    definitions[0] = style(0, papx=outline(6))
    definitions[2] = style(2, base=0)
    assert parse(monkeypatch, source(selected=15, styles=definitions)).blocks == [Paragraph('Title', 7)]


def test_pistd_custom_descendant_uses_raw_outline_cache(monkeypatch):
    definitions = records(style(15, base=2))
    definitions[2] = style(2, papx=outline(4))
    result = parse(monkeypatch, source(selected=2, direct=sprm(0x4600, u16(15)), styles=definitions))
    assert result.blocks == [Paragraph('Title', 5)]
