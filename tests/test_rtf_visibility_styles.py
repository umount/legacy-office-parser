"""Original synthetic fixtures for supported RTF style visibility, never rendering."""
import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph
from legacy_office_parser.rtf import parse_rtf_bytes


def parse(body, **limits):
    return parse_rtf_bytes(br'{\rtf1 ' + body + b'}', Limits(**limits))


def sheet(definitions):
    return br'{\stylesheet' + definitions + b'}'


@pytest.mark.parametrize('flag', [br'\v', br'\deleted'])
@pytest.mark.parametrize('kind', [b's', b'cs'])
def test_inherited_style_flag_forward_base_and_later_visible_style(flag, kind):
    star = b'' if kind == b's' else br'\*'
    styles = sheet(b'{' + star + b'\\' + kind + br'41\sbasedon42 Child;}'
                   b'{' + star + b'\\' + kind + b'42' + flag + b' Base;}'
                   b'{' + star + b'\\' + kind + b'43 Visible;}')
    d = parse(styles + b'\\' + kind + b'41 SECRET' + b'\\' + kind + b'43 Public')
    assert d.text == 'Public'
    assert 'Hidden or deleted text omitted.' in d.warnings


@pytest.mark.parametrize('flag', [br'\v', br'\deleted'])
@pytest.mark.parametrize('kind', [b's', b'cs'])
def test_explicit_false_child_and_scoped_direct_overrides(flag, kind):
    styles = sheet(b'{\\' + kind + b'41' + flag + b' Base;}'
                   b'{\\' + kind + br'42\sbasedon41' + flag + b'0 Child;}')
    d = parse(styles + b'\\' + kind + b'41 SECRET{' + flag + b'0 A}'
              b'SECRET\\' + kind + b'42 B{' + flag + b' SECRET}C')
    assert d.text == 'ABC'


@pytest.mark.parametrize('direct_first', [False, True])
def test_direct_false_wins_over_style_in_both_orders(direct_first):
    body = br'\v0\s41' if direct_first else br'\s41\v0'
    assert parse(sheet(br'{\s41\v Hidden;}') + body + b'Visible').text == 'Visible'


def test_hidden_and_deleted_are_independent_style_properties():
    d = parse(sheet(br'{\s41\v\deleted Base;}{\s42\sbasedon41\v0 Derived;}')
              + br'\s42 SECRET{\deleted0 Visible}SECRET')
    assert d.text == 'Visible'


@pytest.mark.parametrize('additive,expected', [(b'', 'B'), (br'\additive', '')])
def test_character_style_additive_vs_replacement(additive, expected):
    d = parse(sheet(br'{\s41\v Paragraph;}{\*\cs51' + additive + b' Character;}')
              + br'\s41 SECRET\cs51 B')
    assert d.text == expected


def test_additive_character_style_overlays_each_property():
    d = parse(sheet(br'{\s41\v Paragraph;}{\*\cs51\additive\v0\deleted Character;}')
              + br'\s41\cs51 SECRET\deleted0 Visible')
    assert d.text == 'Visible'


def test_character_style_inheritance_has_own_namespace_and_no_heading():
    d = parse(sheet(br'{\s41\outlinelevel3 Heading 4;}'
                    br'{\*\cs41\v Character;}{\*\cs42\sbasedon41 Child;}')
              + br'\s41 A{\cs42 SECRET}B\par\pard C')
    assert d.blocks == [Paragraph('AB', 4), Paragraph('C')]


def test_plain_reset_restores_defaults_and_style_can_be_selected_again():
    d = parse(sheet(br'{\s41\v\outlinelevel1 Heading 2;}{\*\cs51\deleted Character;}')
              + br'\s41 SECRET\plain A\cs51 SECRET\plain B\s41 SECRET\v0 C')
    assert d.blocks == [Paragraph('ABC', 2)]


def test_pard_releases_paragraph_style_without_clearing_direct_visibility():
    d = parse(sheet(br'{\s41\v Hidden;}')
              + br'\s41 SECRET\pard A\v\s41 SECRET\pard SECRET\v0 B')
    assert d.text == 'AB'


def test_default_paragraph_style_visibility_and_plain():
    d = parse(sheet(br'{\s0\deleted Default;}') + br'SECRET\plain Visible')
    assert d.text == 'Visible'


@pytest.mark.parametrize('story', [b'header', b'footer', b'footnote', b'footnote\\ftnalt',
                                  b'shptxt', b'do{\\dptxbxtext'])
@pytest.mark.parametrize('source', [br'\s41', br'\cs51', br'\v', br'\deleted'])
def test_story_entry_does_not_release_inherited_suppression(story, source):
    styles = sheet(br'{\s41\v Hidden;}{\*\cs51\deleted Character;}')
    close = b'}}' if story.startswith(b'do') else b'}'
    d = parse(styles + b'{' + source + b'{\\' + story + b' SECRET' + close + b'}Public')
    assert d.text == 'Public'
    assert not any(getattr(d, k) for k in ('headers_footers', 'footnotes', 'endnotes', 'textboxes'))


def test_explicit_story_override_is_local_to_story():
    d = parse(sheet(br'{\s41\v Hidden;}') + br'\s41 SECRET{\footnote\v0 Note}SECRET\plain Public')
    assert d.footnotes == 'Note'
    assert d.blocks == [Paragraph('Public')]


@pytest.mark.parametrize('selection', [br'\s41', br'\cs51', br'\v', br'\deleted'])
def test_suppressed_ancestor_cannot_publish_styles_or_headings(selection):
    d = parse(sheet(br'{\s41\v Hidden;}{\*\cs51\deleted Character;}')
              + b'{' + selection + sheet(br'{\s61\v\outlinelevel0 Poison;}') + b'}'
              + br'\s61 Public')
    assert d.blocks == [Paragraph('Public')]


@pytest.mark.parametrize('destination', [br'\info', br'\object', br'\*\unknown', br'\fldinst'])
def test_skipped_destinations_cannot_reenable_text_or_define_styles(destination):
    d = parse(b'{' + destination + br'\plain\v0\deleted0\s0\cs0 SECRET'
              + sheet(br'{\s41\v Hidden;}') + br'{\fldrslt SECRET}}\s41 Public')
    assert d.text == 'Public'


def test_field_instruction_styles_are_skipped_and_result_uses_visibility():
    d = parse(sheet(br'{\s41\v Hidden;}{\*\cs51\deleted Character;}')
              + br'{\field{\*\fldinst\s41\cs51 SECRET}{\fldrslt A{\cs51 SECRET}B}}')
    assert d.text == 'AB'


@pytest.mark.parametrize('ignored', [br'\*\unknown', br'\ds41', br'\ts41'])
def test_other_style_kinds_and_optional_definitions_do_not_publish_visibility(ignored):
    d = parse(sheet(b'{' + ignored + br'\s41\v SECRET;}') + br'\s41 Public')
    assert d.text == 'Public'


def test_nested_style_metadata_and_unicode_fallback_cannot_override_visibility():
    d = parse(sheet(br'{\s41\v{\*\keycode\v0}Hidden;}'
                    br'{\s42\v\uc1\u945\v0 Hidden;}')
              + br'\s41 SECRET\s42 SECRET\plain Public')
    assert d.text == 'Public'


@pytest.mark.parametrize('flag', [br'\v', br'\deleted'])
def test_cycle_terminates_and_retains_nearest_explicit_visibility(flag):
    d = parse(sheet(br'{\s41\sbasedon42 A;}{\s42\sbasedon41' + flag + b' B;}')
              + br'\s41 SECRET\s42 SECRET\plain Public')
    assert d.text == 'Public'
    assert any('Cyclic RTF style inheritance' in warning for warning in d.warnings)


def test_cycle_without_visibility_preserves_existing_heading_behavior():
    d = parse(sheet(br'{\s41\sbasedon42 A;}{\s42\sbasedon41 B;}') + br'\s41 Public')
    assert d.text == 'Public'
    assert any('Cyclic RTF style inheritance' in warning for warning in d.warnings)


def test_missing_or_cross_kind_base_warns_but_uses_available_properties():
    d = parse(sheet(br'{\*\cs41\v Character;}{\s42\sbasedon41\deleted Paragraph;}')
              + br'\s42 SECRET\plain Public')
    assert d.text == 'Public'
    assert any('base missing or wrong kind' in warning for warning in d.warnings)


def test_long_style_chain_is_linear_iterative_and_record_bounded():
    definitions = b''.join(fr'{{\s{i}\sbasedon{i+1} Child;}}'.encode()
                           for i in range(1000, 3000))
    body = sheet(definitions + br'{\s3000\v Root;}') + br'\s1000 SECRET\plain Public'
    assert parse(body).text == 'Public'
    with pytest.raises(LimitExceededError):
        parse(body, max_records=100)


@pytest.mark.parametrize('value', [br'\uc-1', br'\uc'])
def test_invalid_style_fallback_count_is_not_swallowed(value):
    with pytest.raises(InvalidDocumentError):
        parse(sheet(br'{\s41' + value + b' Bad;}'))


def test_suppressed_style_text_does_not_consume_retained_text_budget():
    d = parse(sheet(br'{\s41\v Hidden;}') + br'\s41 ' + b'X' * 10000 + br'\plain OK',
              max_text_chars=2)
    assert d.text == 'OK'


def test_hidden_cell_keeps_coordinates_and_visible_neighbor_ownership():
    d = parse(sheet(br'{\s41\v\outlinelevel0 Hidden;}')
              + br'\trowd\cellx100\cellx200\intbl\s41 SECRET\cell'
              br'\s0 Public\cell\row')
    assert [c.text for c in d.blocks[0].rows[0]] == ['', 'Public']
    assert d.blocks[0].rows[0][0].blocks == []


def test_hidden_paragraph_mark_does_not_join_visible_paragraphs():
    d = parse(sheet(br'{\*\cs41\v Character;}') + br'A{\cs41 SECRET\par}B')
    assert d.blocks == [Paragraph('A'), Paragraph('B')]


def test_nested_hidden_cell_keeps_parent_and_following_text_separate():
    d = parse(sheet(br'{\s41\v Hidden;}')
              + br'\trowd\cellx400\intbl Before\par'
              br'\pard\intbl\itap2\s41 SECRET\nestcell'
              br'{\*\nesttableprops\trowd\cellx200\nestrow}'
              br'\pard\intbl After\cell\row')
    cell = d.blocks[0].rows[0][0]
    assert cell.blocks[0] == Paragraph('Before')
    assert cell.blocks[1].rows[0][0].text == ''
    assert cell.blocks[2] == Paragraph('After')


def test_hidden_style_cannot_enable_wordart_property_projection():
    from test_rtf_wordart import shape
    d = parse(sheet(br'{\s41\v Hidden;}') + br'{\s41 ' + shape(b'SECRET') + b'}Public')
    assert d.text == 'Public'
    assert not d.textboxes


def test_style_hidden_is_not_the_style_menu_shidden_flag():
    assert parse(sheet(br'{\s41\shidden HiddenInMenu;}') + br'\s41 Public').text == 'Public'


def test_unicode_fallback_binary_is_opaque_in_stylesheet():
    d = parse(sheet(br'{\s41\v\uc1\u945\bin3 xxx Hidden;}') + br'\s41 SECRET\plain Public')
    assert d.text == 'Public'


def test_replacement_character_style_releases_inherited_deletion():
    d = parse(sheet(br'{\s41\deleted Paragraph;}{\*\cs51 Clear;}') + br'\s41 SECRET\cs51 Public')
    assert d.text == 'Public'


def test_style_group_depth_and_unicode_fallback_have_existing_limits():
    with pytest.raises(LimitExceededError):
        parse(sheet(br'{\s41{\*\keycode{Deep}}\v Hidden;}'), max_depth=3)
    with pytest.raises(LimitExceededError):
        parse(sheet(br'{\s41\uc1000\v Hidden;}'), max_stream_bytes=100)


def test_plain_inside_style_definition_overrides_inherited_flags():
    d = parse(sheet(br'{\s41\v\deleted Base;}{\s42\sbasedon41\plain Child;}')
              + br'\s42 Public')
    assert d.text == 'Public'


def test_style_group_override_restores_parent_character_selection():
    d = parse(sheet(br'{\*\cs41\v Hidden;}{\*\cs42 Visible;}')
              + br'\cs41 SECRET{\cs42 A}SECRET\plain B')
    assert d.text == 'AB'


def test_hidden_style_does_not_consume_or_publish_visible_unicode_surrogate():
    d = parse(sheet(br'{\s41\v Hidden;}')
              + br'\u55357\s41 SECRET\u56832?\plain A')
    # The style control is the fallback for the high surrogate here, so no
    # style change occurs. A separate direct test below exercises the switch.
    assert d.text == '\ufffdSECRET\ufffdA'
    d = parse(sheet(br'{\s41\v Hidden;}')
              + br'\uc0\u55357\s41 SECRET\u56832\plain A')
    assert d.text == '\ufffdA'
