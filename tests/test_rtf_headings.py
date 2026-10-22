"""Original synthetic RTF fixtures; no user document content."""
import pytest

from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes


def parse(body, **limits):
    return parse_rtf_bytes(b'{\\rtf1 ' + body + b'}', Limits(**limits))


def levels(doc):
    return [p.heading_level for p in doc.blocks if isinstance(p, Paragraph)]


@pytest.mark.parametrize('outline', range(10))
def test_direct_levels_and_json(outline):
    d = parse(fr'\outlinelevel{outline} Alpha\par Beta\par\pard Gamma'.encode())
    expected = outline + 1 if outline < 9 else None
    assert levels(d) == [expected, expected, None]
    assert d.text == 'Alpha\n\nBeta\n\nGamma'
    assert 'heading_level' not in d.to_dict()['blocks'][-1]
    assert d.to_dict()['blocks'][0].get('heading_level') == expected


@pytest.mark.parametrize('control', [b'\\outlinelevel', b'\\outlinelevel-1', b'\\outlinelevel10'])
def test_invalid_outline_does_not_replace_valid_property(control):
    assert levels(parse(b'\\outlinelevel2 ' + control + b' Alpha')) == [3]


def test_scoped_properties_plain_and_paragraph_ends():
    d = parse(br'\outlinelevel1 A\par{\outlinelevel4 B\par}C\par'
              br'\plain D\par\pard E\par\outlinelevel8\par')
    assert levels(d) == [2, 5, 2, 2, None, 9]
    assert d.text == 'A\n\nB\n\nC\n\nD\n\nE'


def test_late_properties_and_unterminated_group():
    assert levels(parse(br'Alpha\outlinelevel3\par')) == [4]
    assert levels(parse(br'{\outlinelevel3 Alpha}')) == [4]
    assert levels(parse(br'\outlinelevel3 Alpha\pard\par')) == [None]


def test_style_inheritance_forward_bases_body_and_direct_override():
    d = parse(br'{\stylesheet{\s41\sbasedon42 Derived;}'
              br'{\s42\outlinelevel2 Base;}{\s43\sbasedon41\outlinelevel9 Body;}}'
              br'\s41 A\par B\par\pard\s43 C\par'
              br'\pard\outlinelevel5\s41 D\par\pard E')
    assert levels(d) == [3, 3, None, 6, None]
    assert d.text == 'A\n\nB\n\nC\n\nD\n\nE'


def test_cycles_missing_bases_nonparagraph_and_nested_properties():
    d = parse(br'{\stylesheet{\s41\sbasedon42 A;}{\s42\sbasedon41 B;}'
              br'{\s43\sbasedon99 C;}{\*\cs44\outlinelevel0 Character;}'
              br'{\s45{\*\unknown\outlinelevel0} D;}}'
              br'\s41 A\par\s43 B\par\s44 C\par\s45 D')
    assert levels(d) == [None] * 4


@pytest.mark.parametrize('prefix', [b'heading ', b'Heading '])
@pytest.mark.parametrize('level', range(1, 10))
def test_builtin_names_exact_and_inherited(prefix, level):
    d = parse(b'{\\stylesheet{\\s71 ' + prefix + str(level).encode() +
              br';}{\s72\sbasedon71 Derived;}}\s72 Alpha')
    assert levels(d) == [level]
    assert d.warnings == ['RTF heading levels inferred from built-in style names.']


@pytest.mark.parametrize('name', [b'Heading 10', b'heading 0', b'Heading 2 Custom',
                                 b'HEADING 2', b'Heading 02', b'heading  2',
                                 b'X' * 10000 + b'Heading 2'])
def test_no_name_or_style_number_guessing(name):
    assert levels(parse(b'{\\stylesheet{\\s2 ' + name + b';}}\\s2 Alpha')) == [None]


def test_explicit_body_overrides_builtin_and_inherited_name():
    d = parse(br'{\stylesheet{\s71\outlinelevel9 Heading 2;}'
              br'{\s72 heading 3;}{\s73\sbasedon72\outlinelevel9 Derived;}}'
              br'\s71 A\par\s73 B\par\s72\outlinelevel9 C')
    assert levels(d) == [None] * 3


def test_ignored_destinations_do_not_define_styles_or_headings():
    d = parse(br'{\info{\stylesheet{\s71\outlinelevel1 Fake;}}}'
              br'{\*\unknown\outlinelevel2 Bad}'
              br'\s71 A{\v\outlinelevel3 Hidden}{\deleted\outlinelevel4 Gone}'
              br'{\field{\*\fldinst\outlinelevel5 Instruction}{\fldrslt Result}}')
    assert d.text == 'AResult'
    assert levels(d) == [None]


def test_cell_paragraphs_keep_heading_ownership_and_exact_projection():
    d = parse(br'\trowd\cellx100\cellx200\intbl\outlinelevel1 A\par'
              br'\pard\intbl B\line C\par\cell D\cell\row\pard End')
    a, b = d.blocks[0].rows[0]
    assert a.text == 'A\nB\nC\n'
    assert a.blocks == [Paragraph('A', 2), Paragraph('B\nC')]
    assert b.text == 'D' and not b.blocks
    assert d.text == 'A\nB\nC\n\tD\n\nEnd'


def test_nested_heading_and_parent_are_separate():
    d = parse(br'\trowd\cellx300\intbl\outlinelevel0 Outer\par'
              br'\pard\intbl\itap2\outlinelevel2 Inner\nestcell'
              br'{\*\nesttableprops\trowd\cellx200\nestrow}'
              br'\pard\intbl After\cell\row\pard End')
    outer = d.blocks[0].rows[0][0]
    assert outer.blocks[0] == Paragraph('Outer', 1)
    assert isinstance(outer.blocks[1], Table)
    assert outer.blocks[1].rows[0][0].blocks == [Paragraph('Inner', 3)]
    assert outer.blocks[2] == Paragraph('After')
    assert d.blocks[-1] == Paragraph('End')


@pytest.mark.parametrize('control,story', [(b'header', 'headers_footers'),
                                         (b'footnote', 'footnotes'),
                                         (b'footnote\\ftnalt', 'endnotes'),
                                         (b'shptxt', 'textboxes')])
def test_auxiliary_story_blocks_include_all_siblings(control, story):
    d = parse(b'{\\' + control + br'\pard First}' + b'{\\' + control +
              br'\pard\outlinelevel3 Second}Body')
    assert getattr(d, story) == 'First\nSecond'
    assert d.story_blocks[story] == [Paragraph('First'), Paragraph('Second', 4)]
    assert d.blocks == [Paragraph('Body')]


def test_merged_cell_transfers_blocks_without_covered_duplicates():
    d = parse(br'\trowd\clmgf\cellx100\clmrg\cellx200'
              br'\intbl\outlinelevel1 A\cell\pard\intbl B\cell\row')
    a, b = d.blocks[0].rows[0]
    assert a.text == 'A\nB'
    assert a.blocks == [Paragraph('A', 2), Paragraph('B')]
    assert b.covered and b.text == '' and b.blocks == []


@pytest.mark.parametrize('body,budget', [
    (br'\trowd\cellx100\intbl\outlinelevel0 ABC\cell\row', 6),
    (br'{\header\outlinelevel0 ABC}', 6),
    (br'{\header ABC}{\header\outlinelevel0 D}', 10),
])
def test_retained_heading_projections_are_budgeted(body, budget):
    parse(body, max_text_chars=budget)
    with pytest.raises(LimitExceededError):
        parse(body, max_text_chars=budget - 1)


def test_long_style_chain_is_iterative_and_lexically_bounded():
    styles = b''.join(fr'{{\s{i}\sbasedon{i+1} S;}}'.encode() for i in range(1000, 2500))
    body = b'{\\stylesheet' + styles + br'{\s2500\outlinelevel7 Root;}}\s1000 A'
    assert levels(parse(body)) == [8]
    with pytest.raises(LimitExceededError):
        parse(body, max_records=50)


def test_merge_heading_in_continuation_keeps_plain_anchor_once():
    d = parse(br'\trowd\clmgf\cellx100\clmrg\cellx200'
              br'\intbl A\cell\outlinelevel1 B\cell\row')
    a, b = d.blocks[0].rows[0]
    assert a.text == 'A\nB'
    assert a.blocks == [Paragraph('A'), Paragraph('B', 2)]
    assert not b.blocks


def test_optional_stylesheet_group_cannot_define_default_heading():
    d = parse(br'{\stylesheet{\*\unknown\outlinelevel0 NotAStyle;}}Alpha')
    assert levels(d) == [None]


def test_builtin_name_does_not_read_nested_destination_text():
    d = parse(br'{\stylesheet{\s71{\*\keycode heading 1;}Custom;}}\s71 Alpha')
    assert levels(d) == [None]


def test_empty_heading_cell_and_following_body_cell():
    d = parse(br'\trowd\cellx100\cellx200\intbl\outlinelevel2\par\cell'
              br'\pard\intbl Plain\cell\row')
    a, b = d.blocks[0].rows[0]
    assert a.blocks == [Paragraph('', 3)]
    assert a.text == '\n'
    assert b.text == 'Plain' and not b.blocks


def test_explicit_empty_heading_cell_has_a_paragraph():
    d = parse(br'\trowd\cellx100\intbl\outlinelevel2\cell\row')
    assert d.blocks[0].rows[0][0].blocks == [Paragraph('', 3)]
    assert d.blocks[0].rows[0][0].text == ''


def test_default_style_and_pard_reapply_default_properties():
    d = parse(br'{\stylesheet{\outlinelevel1 Default;}}A\par'
              br'\outlinelevel9 B\par\pard C')
    assert levels(d) == [2, None, 2]


def test_hex_escaped_builtin_name_and_whitespace():
    d = parse(br"{\stylesheet{\s71 \'68eading 4 ;}}\s71 Alpha")
    assert levels(d) == [4]


def test_plain_documents_keep_legacy_cell_and_story_shape():
    d = parse(br'{\header Header}\trowd\cellx100\intbl A\par B\cell\row')
    assert not d.story_blocks
    assert not d.blocks[0].rows[0][0].blocks
    assert 'heading_level' not in str(d.to_dict())


@pytest.mark.parametrize('suppression', [br'\v', br'\deleted'])
@pytest.mark.parametrize('definition', [br'\outlinelevel1 Custom;', b'Heading 2;'])
def test_suppressed_stylesheet_cannot_publish_or_replace_style(suppression, definition):
    d = parse(br'{\stylesheet{\s81\outlinelevel4 Visible;}}'
              b'{' + suppression + br'{\stylesheet{\s81 ' + definition + b'}}}'
              br'\s81 Kept\par\pard Body')
    assert d.blocks == [Paragraph('Kept', 5), Paragraph('Body')]
    assert not any('inferred' in warning for warning in d.warnings)


@pytest.mark.parametrize('prefix', [br'\outlinelevel4',
                                   br'{\stylesheet{\s0\outlinelevel4 Default;}}'])
def test_consecutive_empty_cells_inherit_heading_until_reset(prefix):
    d = parse(prefix + br'\trowd\cellx100\cellx200\cellx300\intbl'
              br'\cell\cell\pard\outlinelevel9\intbl\cell\row')
    cells = d.blocks[0].rows[0]
    assert [cell.blocks for cell in cells] == [[Paragraph('', 5)], [Paragraph('', 5)], []]
    assert [cell.text for cell in cells] == ['', '', '']


@pytest.mark.parametrize('inner', [br'\outlinelevel3', br'\s81'])
@pytest.mark.parametrize('separator', [b'', br'\par'])
def test_nested_transition_keeps_parent_heading_with_implicit_boundary(inner, separator):
    d = parse(br'{\stylesheet{\s81\outlinelevel3 Child;}}'
              br'\trowd\cellx400\intbl\outlinelevel1 Before' + separator +
              br'\pard\intbl\itap2' + inner + br' Child\nestcell'
              br'{\*\nesttableprops\trowd\cellx200\nestrow}'
              br'\pard\intbl After\cell\row')
    cell = d.blocks[0].rows[0][0]
    assert cell.blocks[0] == Paragraph('Before', 2)
    assert cell.blocks[1].rows[0][0].blocks == [Paragraph('Child', 4)]
    assert cell.blocks[2] == Paragraph('After')
    assert cell.text == 'Before\nChild\nAfter'


@pytest.mark.parametrize('body_override', [br'\outlinelevel9\s81', br'\s81\outlinelevel9'])
def test_exact_builtin_compatibility_yields_to_explicit_body_in_either_order(body_override):
    d = parse(br'{\stylesheet{\s81 Heading 6;}}\s81 Heading\par'
              + body_override + br' Body\par\pard\s81 Restored')
    assert d.blocks == [Paragraph('Heading', 6), Paragraph('Body'), Paragraph('Restored', 6)]
