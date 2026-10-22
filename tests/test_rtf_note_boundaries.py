"""Original synthetic RTF note identities; no source offset or anchor guesses."""
import pytest

from legacy_office_parser import parse_rtf
from legacy_office_parser.errors import LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Note, NoteBodyRange, Paragraph, Table


def parse(body, **limits):
    return parse_rtf(br'{\rtf1 ' + body + b'}', limits=Limits(**limits))


def test_individual_ranges_per_kind_and_no_duplicate_text_projection():
    d = parse(br'Body{\footnote First\par Second}{\footnote\ftnalt End}'
              br'{\footnote Last}Tail')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 2)),
                       Note('endnote', 1, NoteBodyRange('endnotes', 0, 1)),
                       Note('footnote', 2, NoteBodyRange('footnotes', 2, 3))]
    assert d.story_blocks['footnotes'] == [Paragraph('First'), Paragraph('Second'), Paragraph('Last')]
    assert d.story_blocks['endnotes'] == [Paragraph('End')]
    assert d.text == 'BodyTail\n\nFirst\nSecond\nLast\n\nEnd'
    assert d.footnotes == 'First\nSecond\nLast' and d.endnotes == 'End'
    for note in d.notes:
        assert note.source_cp is None and note.anchor_path is None
        assert note.reference_kind == 'unknown' and note.visibility == ['unknown']


def test_empty_notes_have_nonempty_disjoint_body_ranges():
    d = parse(br'{\footnote}{\footnote\ftnalt}{\footnote\par}{\footnote X}{\footnote}')
    assert [(n.kind, n.ordinal, n.body.block_start, n.body.block_end) for n in d.notes] == [
        ('footnote', 1, 0, 1), ('endnote', 1, 0, 1), ('footnote', 2, 1, 2),
        ('footnote', 3, 2, 3), ('footnote', 4, 3, 4)]
    assert d.story_blocks['footnotes'] == [Paragraph(''), Paragraph(''), Paragraph('X'), Paragraph('')]
    assert d.footnotes == 'X' and d.endnotes == '' and d.text == 'X'


def test_identical_notes_are_distinct_and_not_deduplicated():
    d = parse(br'{\footnote Same}{\footnote Same}')
    assert len(d.notes) == 2
    assert d.notes[0].body != d.notes[1].body
    assert d.story_blocks['footnotes'][0] is not d.story_blocks['footnotes'][1]
    assert d.footnotes == 'Same\nSame'


def test_note_in_body_table_preserves_ownership_without_anchor_guess():
    d = parse(br'\trowd\cellx100\intbl A{\footnote Note}B\cell\row')
    assert d.blocks[0].rows[0][0].text == 'AB'
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.footnotes == 'Note'


def test_table_and_heading_inside_note_are_in_its_single_range():
    d = parse(br'{\footnote\outlinelevel1 Title\par\pard'
              br'\trowd\cellx100\intbl Cell\cell\row\pard After}')
    blocks = d.story_blocks['footnotes']
    assert blocks[0] == Paragraph('Title', 2)
    assert isinstance(blocks[1], Table) and blocks[1].rows[0][0].text == 'Cell'
    assert blocks[2] == Paragraph('After')
    assert d.notes[0].body == NoteBodyRange('footnotes', 0, 3)
    assert d.footnotes == 'Title\nCell\nAfter'


def test_ftnalt_classifies_root_without_closing_nested_table():
    d = parse(br'{\footnote\trowd\cellx300\intbl Outer\par'
              br'\pard\intbl\itap2\ftnalt Inner\nestcell'
              br'{\*\nesttableprops\trowd\cellx100\nestrow}'
              br'\pard\intbl After\cell\row}')
    assert d.notes == [Note('endnote', 1, NoteBodyRange('endnotes', 0, 1))]
    assert d.endnotes == 'Outer\nInner\nAfter'
    assert not d.footnotes


@pytest.mark.parametrize('ancestor', [br'\info', br'\pict', br'\object', br'\*\unknown',
                                     br'\fldinst', br'\fonttbl', br'\shp', br'\do'])
def test_skipped_or_unsupported_ancestors_do_not_create_note_identity(ancestor):
    d = parse(b'{' + ancestor + br'{\footnote\ftnalt SECRET}}Public')
    assert not d.notes
    assert not d.footnotes and not d.endnotes
    assert d.text == 'Public'


@pytest.mark.parametrize('flag', [br'\v', br'\deleted', br'\s41', br'\cs51'])
def test_fully_hidden_note_sink_does_not_invent_empty_note(flag):
    d = parse(br'{\stylesheet{\s41\v Hidden;}{\*\cs51\deleted Hidden;}}'
              b'{' + flag + br'{\footnote SECRET}}{\footnote Public}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.story_blocks['footnotes'] == [Paragraph('Public')]
    assert d.footnotes == 'Public'


def test_explicit_visibility_override_inside_note_retains_existing_behavior():
    d = parse(br'{\v{\footnote\v0 Public}}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.footnotes == 'Public'


def test_nested_note_is_omitted_not_merged_or_given_an_identity():
    d = parse(br'{\footnote A{\footnote\ftnalt SECRET}B}{\footnote C}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1)),
                       Note('footnote', 2, NoteBodyRange('footnotes', 1, 2))]
    assert d.footnotes == 'AB\nC' and d.endnotes == ''
    assert 'RTF note destination in an auxiliary story omitted.' in d.warnings


@pytest.mark.parametrize('story', [b'header', b'footer', b'shptxt'])
def test_notes_in_auxiliary_stories_do_not_invent_body_references(story):
    d = parse(b'{\\' + story + br' A{\footnote SECRET}B}{\footnote Note}')
    assert len(d.notes) == 1 and d.footnotes == 'Note'
    assert 'SECRET' not in d.text


def test_note_separators_and_unscoped_ftnalt_do_not_create_notes():
    d = parse(br'{\ftnsep{\footnote SECRET}}{\aftnsep Separator}\ftnalt Body')
    assert d.notes == [] and d.text == 'Body'


def test_unicode_fallback_note_control_is_not_executed():
    d = parse(br'\u945\footnote Public')
    assert not d.notes and d.text == 'αPublic'


def test_hidden_ftnalt_does_not_reclassify_visible_note():
    d = parse(br'{\footnote A{\v\ftnalt SECRET}B}')
    assert d.notes[0].kind == 'footnote' and d.footnotes == 'AB'


@pytest.mark.parametrize('body,budget', [
    (br'{\footnote ABC}', 6),
    (br'{\footnote A}{\footnote B}', 6),
    (br'{\footnote A\par B}', 6),
    (br'{\footnote\trowd\cellx100\cellx200 A\cell B\cell\row}', 6),
])
def test_note_blocks_and_aggregate_projection_are_both_budgeted(body, budget):
    assert parse(body, max_text_chars=budget).notes
    with pytest.raises(LimitExceededError):
        parse(body, max_text_chars=budget - 1)


def test_note_records_are_bounded_by_existing_record_limit():
    body = br'{\footnote}' * 100
    assert len(parse(body).notes) == 100
    with pytest.raises(LimitExceededError):
        parse(body, max_records=50)


def test_note_json_has_unknown_reference_metadata_and_valid_range():
    item = parse(br'{\footnote Note}').to_dict()['notes'][0]
    assert item == {'kind': 'footnote', 'ordinal': 1,
                    'body': {'story': 'footnotes', 'block_start': 0, 'block_end': 1},
                    'source_cp': None, 'reference_kind': 'unknown',
                    'anchor_path': None, 'visibility': ['unknown']}


def test_hidden_endnote_declaration_survives_explicit_body_visibility_override():
    d = parse(br'{\v{\footnote\ftnalt\v0 Note}}')
    assert d.notes == [Note('endnote', 1, NoteBodyRange('endnotes', 0, 1))]
    assert d.endnotes == 'Note' and d.footnotes == ''


def test_completely_filtered_body_of_visible_note_retains_empty_identity():
    d = parse(br'{\footnote{\v SECRET}}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.story_blocks['footnotes'] == [Paragraph('')]
    assert d.footnotes == ''


def test_hidden_structural_note_sink_does_not_promote_itself_during_finish():
    d = parse(br'{\v{\footnote\trowd\cellx100 SECRET\cell\row}}')
    assert d.notes == [] and d.story_blocks == {} and d.footnotes == ''


def test_field_results_inside_each_note_stay_in_their_own_ranges():
    d = parse(br'{\footnote{\field{\*\fldinst SECRET}{\fldrslt First}}}'
              br'{\footnote{\field{\*\fldinst SECRET}{\fldrslt Second}}}')
    assert d.story_blocks['footnotes'] == [Paragraph('First'), Paragraph('Second')]
    assert [n.body for n in d.notes] == [NoteBodyRange('footnotes', 0, 1),
                                        NoteBodyRange('footnotes', 1, 2)]
    assert d.text == 'First\nSecond'


def test_nested_note_cannot_reopen_through_plain_or_field_result():
    d = parse(br'{\footnote A{\footnote\plain{\fldrslt SECRET}}B}')
    assert len(d.notes) == 1 and d.footnotes == 'AB'


def test_each_endnote_ordinal_uses_encounter_order_not_footnote_count():
    d = parse(br'{\footnote\ftnalt A}{\footnote B}{\footnote\ftnalt C}'
              br'{\footnote\ftnalt D}{\footnote E}')
    assert [(n.kind, n.ordinal) for n in d.notes] == [
        ('endnote', 1), ('footnote', 1), ('endnote', 2), ('endnote', 3), ('footnote', 2)]
    assert [n.body.block_start for n in d.notes] == [0, 0, 1, 2, 1]


def test_metadata_budget_is_checked_before_note_record_allocation():
    # Exercise the independent finalization bound. Normal public parsing also
    # checks lexical records, which is necessarily tighter for empty notes.
    from legacy_office_parser.rtf import _Parser, _Sink
    parser = _Parser(Limits(max_records=1))
    parser.sinks.extend([_Sink(parser, 'footnotes'), _Sink(parser, 'footnotes')])
    with pytest.raises(LimitExceededError, match='RTF note metadata limit exceeded'):
        parser._finalize_auxiliary_stories()
    assert len(parser.document.notes) == 1


@pytest.mark.parametrize('prefix,reset', [
    (br'\v', br'\v0'), (br'\v', br'\plain'), (br'\s41', br'\pard'),
    (br'\deleted', br'\deleted0'), (br'\s41', br'\s0'), (br'\cs51', br'\cs52'),
])
@pytest.mark.parametrize('marker,story,kind', [(b'', 'footnotes', 'footnote'),
                                            (br'\ftnalt', 'endnotes', 'endnote')])
def test_explicitly_revealed_empty_note_has_its_own_range(prefix, reset, marker, story, kind):
    styles = br'{\stylesheet{\s41\v Hidden;}{\*\cs51\deleted Hidden;}{\*\cs52 Clear;}}'
    d = parse(styles + b'{' + prefix + br'{\footnote' + marker + reset + b'}}'
              + br'{\footnote' + marker + b' Last}')
    assert d.notes == [Note(kind, 1, NoteBodyRange(story, 0, 1)),
                       Note(kind, 2, NoteBodyRange(story, 1, 2))]
    assert d.story_blocks[story] == [Paragraph(''), Paragraph('Last')]
    assert getattr(d, story) == 'Last' and d.text == 'Last'


@pytest.mark.parametrize('reset', [br'\v0', br'\plain', br'\pard'])
def test_reset_in_skipped_note_child_does_not_reveal_empty_note(reset):
    d = parse(br'{\v{\footnote{\*\unknown' + reset + b'}}}' + br'{\footnote Last}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.story_blocks['footnotes'] == [Paragraph('Last')]


def test_reset_that_leaves_another_suppression_flag_does_not_reveal_note():
    d = parse(br'{\v\deleted{\footnote\v0}}{\footnote Last}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.story_blocks['footnotes'] == [Paragraph('Last')]


def test_unicode_fallback_reset_does_not_reveal_empty_note():
    d = parse(br'{\v{\footnote\u945\plain}}{\footnote Last}')
    assert d.notes == [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1))]
    assert d.story_blocks['footnotes'] == [Paragraph('Last')]
