"""Original optional-part audit; distinguish format-supported absence from tolerance."""
import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits, parse_rtf
from legacy_office_parser.models import Paragraph


def document(extra=b'', body=b'Body'):
    return b'{\\rtf1\\ansi\\deff0 ' + extra + body + b'}'


@pytest.mark.parametrize('extra', [
    b'', br'{\info}', br'{\info{\title}{\author}{\subject}{\keywords}}',
    br'{\info\nofwords0\nofchars0\edmins0}',
    br'{\info{\creatim}{\revtim}{\printim}{\buptim}}',
    br'{\fonttbl{\f0\fnil Test;}}',
    br'{\fonttbl{\f0\fnil Test;}}{\colortbl;}',
    br'{\fonttbl{\f0\fnil Test;}}{\stylesheet{\s0 Normal;}}',
    br'{\*\generator}', br'{\*\unknown}',
    br'{\*\htmltag64}',
])
def test_absent_optional_tables_or_empty_metadata_preserve_body(extra):
    result = parse_rtf(document(extra))
    assert result.blocks == [Paragraph('Body')]
    assert result.text == 'Body'
    assert not result.notes and not result.comments and not result.story_blocks
    assert result.footnotes == result.endnotes == result.headers_footers == result.textboxes == ''


@pytest.mark.parametrize('destination', [
    b'fonttbl', b'stylesheet', b'colortbl', b'filetbl', b'revtbl', b'rsidtbl',
    b'listtable', b'listoverridetable', b'latentstyles', b'xmlnstbl',
    b'pict', b'object', b'annotation',
])
def test_empty_destination_tolerance_is_not_a_validity_claim(destination):
    # Some table grammars require entries. Record tolerance, not normative validity.
    result = parse_rtf(document(b'{\\' + destination + b'}'))
    assert result.text == 'Body'
    assert result.blocks == [Paragraph('Body')]


@pytest.mark.parametrize('destination', [
    b'header', b'footer', b'headerl', b'headerr', b'headerf', b'footerl', b'footerr', b'footerf',
    b'ftnsep', b'ftnsepc', b'ftncn', b'aftnsep', b'aftnsepc', b'aftncn',
])
@pytest.mark.parametrize('ending', [b'', br'\pard\plain\par'])
def test_empty_auxiliary_story_or_separator_does_not_require_text(destination, ending):
    result = parse_rtf(document(b'{\\' + destination + ending + b'}'))
    assert result.text == 'Body'
    assert result.headers_footers == result.footnotes == result.endnotes == ''
    assert not result.notes


@pytest.mark.parametrize('extra,story', [(br'{\footnote}', 'footnotes'),
                                        (br'{\footnote\ftnalt}', 'endnotes')])
def test_empty_note_keeps_explicit_empty_body_not_invented_anchor(extra, story):
    result = parse_rtf(document(extra))
    assert result.text == 'Body'
    assert getattr(result, story) == ''
    assert result.story_blocks[story] == [Paragraph('')]
    assert len(result.notes) == 1
    note = result.notes[0]
    assert (note.body.story, note.body.block_start, note.body.block_end) == (story, 0, 1)
    assert note.source_cp is None and note.anchor_path is None


@pytest.mark.parametrize('field', [br'{\field{\*\fldinst DATE}}',
                                    br'{\field{\*\fldinst DATE}{\fldrslt}}',
                                    br'{\field{\*\fldinst DATE}{\fldrslt Cached}}'])
def test_missing_or_empty_field_result_is_not_evaluated(field):
    result = parse_rtf(document(body=b'A' + field + b'B'))
    assert result.text == ('ACachedB' if b'Cached' in field else 'AB')
    assert 'DATE' not in result.text


def test_optional_unknown_cannot_reopen_body_or_change_encoding():
    extra = br'{\*\future{\header LEAK}{\footnote LEAK}{\fldrslt LEAK}\ansicpg0\uc-1\itap0}'
    result = parse_rtf(document(extra, br"caf\'e9"))
    assert result.text == 'café'
    assert not result.notes and result.headers_footers == ''
    assert sum(d.code == 'rtf_unknown_optional_destinations_omitted' for d in result.diagnostics) == 1


@pytest.mark.parametrize('payload', [
    br'{\rtf1{\*\future',
    br'{\rtf1{\*\future\bin100 x}}',
    br'{\rtf1{\*\future\bin-1 x}}',
    br"{\rtf1{\*\future\'zz}}",
    b'{\\rtf1{\\*\\future\\',
    br'{\rtf1 Body}}', br'{\rtf1 Body}trailing',
])
def test_optional_does_not_hide_lexical_corruption(payload):
    with pytest.raises(InvalidDocumentError):
        parse_rtf(payload)


@pytest.mark.parametrize('control', [br'\ansicpg0', br'\uc-1', br'\u999999',
                                      br'\nesttableprops', br'\itap-1'])
def test_invalid_present_body_controls_still_fail(control):
    with pytest.raises(InvalidDocumentError):
        parse_rtf(document(body=control + b' Body'))


def test_optional_groups_obey_exact_depth_budget():
    payload = document(br'{\*\future{}}')
    assert parse_rtf(payload, limits=Limits(max_depth=3)).text == 'Body'
    with pytest.raises(LimitExceededError, match='depth'):
        parse_rtf(payload, limits=Limits(max_depth=2))


def test_empty_metadata_repetition_still_obeys_record_limit():
    with pytest.raises(LimitExceededError, match='record'):
        parse_rtf(document(br'{\info}' * 30), limits=Limits(max_records=20))


def test_skipped_binary_is_consumed_exactly_and_source_limits_remain():
    payload = document(br'{\*\future\bin3 }{}}')
    assert parse_rtf(payload).text == 'Body'
    with pytest.raises(LimitExceededError):
        parse_rtf(payload, limits=Limits(max_stream_bytes=len(payload)-1))
    with pytest.raises(LimitExceededError):
        parse_rtf(payload, limits=Limits(max_file_bytes=len(payload)-1))


def test_empty_auxiliary_stories_do_not_reset_text_budget():
    payload = document(br'{\header}{\footer}{\info}', b'12345')
    assert parse_rtf(payload, limits=Limits(max_text_chars=5)).text == '12345'
    with pytest.raises(LimitExceededError, match='text'):
        parse_rtf(payload, limits=Limits(max_text_chars=4))


def test_absent_codepage_font_and_unicode_fallback_metadata_use_existing_defaults():
    result = parse_rtf(br"{\rtf1\deff0 caf\'e9 \u233?}")
    assert result.text == 'café é'


def test_missing_style_base_does_not_refuse_visible_body():
    result = parse_rtf(document(br'{\stylesheet{\s1\sbasedon99 Test;}}', br'\s1 Body'))
    assert result.text == 'Body'
    assert any(d.code == 'rtf_style_base_missing_or_wrong_kind_only_available'
               for d in result.diagnostics)


def test_unsupported_positive_codepage_keeps_existing_explicit_fallback():
    result = parse_rtf(document(body=br"\ansicpg99999 caf\'e9"))
    assert result.text == 'café'
    assert any(d.code == 'rtf_unsupported_code_page_replaced_with_windows_1252'
               for d in result.diagnostics)
