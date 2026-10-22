"""Independent synthetic contracts for DOC auxiliary metadata (no source files)."""
from dataclasses import asdict, replace
import json

import pytest

from legacy_office_parser import AuxiliaryStory
from legacy_office_parser.models import (
    Cell, Comment, CommentBodyRange, Document, Note,
    NoteBodyRange, Paragraph, Table,
)
from legacy_office_parser._serialization import clone_model
from legacy_office_parser._validation import _validate_result
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.normalization import normalize_text


def header(**changes):
    item = replace(AuxiliaryStory('header', 8, 'headers_footers', 0, 1,
                                  0, 4, 'header', 'odd', 1), **changes)
    if 'ordinal' not in changes:
        slots = {('header', 'even'): 0, ('header', 'odd'): 1,
                 ('footer', 'even'): 2, ('footer', 'odd'): 3,
                 ('header', 'first'): 4, ('footer', 'first'): 5}
        if (item.kind, item.variant) in slots and type(item.section) is int:
            item.ordinal = 7 + (item.section - 1) * 6 + slots[item.kind, item.variant]
        elif item.kind in ('footnote_separator', 'endnote_separator'):
            variants = ('separator', 'continuation_separator', 'continuation_notice')
            if item.variant in variants:
                item.ordinal = 1 + variants.index(item.variant) + 3 * (item.kind == 'endnote_separator')
    return item


def textbox(**changes):
    return replace(AuxiliaryStory('main_textbox', 3, 'textboxes', 0, 1,
                                  0, 4, 'textbox'), **changes)


def document(*items):
    return Document('doc', headers_footers='head', textboxes='box',
                    story_blocks={'headers_footers': [Paragraph('head')],
                                  'textboxes': [Paragraph('box')]},
                    auxiliary_stories=list(items or [header()]))


def validate(doc, **limits):
    return _validate_result(doc, replace(Limits(), **limits))


@pytest.mark.parametrize('kind', ['header', 'footer'])
@pytest.mark.parametrize('variant', ['even', 'odd', 'first'])
def test_header_identity(kind, variant):
    doc = document(header(kind=kind, variant=variant))
    assert validate(doc) is doc


@pytest.mark.parametrize('kind', ['footnote_separator', 'endnote_separator'])
@pytest.mark.parametrize('variant', ['separator', 'continuation_separator', 'continuation_notice'])
def test_separator_identity(kind, variant):
    assert validate(document(header(kind=kind, variant=variant, section=None)))


@pytest.mark.parametrize('source', ['main_textbox', 'header_textbox'])
def test_textbox_gapped_plc_ordinals_and_subdocument_relative_positions(source):
    doc = document(textbox(source=source), textbox(source=source, ordinal=12,
                     block_start=1, block_end=2, source_start=4, source_end=8))
    doc.story_blocks['textboxes'].append(Paragraph('next'))
    assert validate(doc) is doc


def test_empty_and_inherited_header_slots_do_not_clone_text():
    first = header()
    inherited = header(ordinal=14, section=2, block_start=1, block_end=1,
                       source_start=4, source_end=4, inherited_from=8)
    empty = header(ordinal=13, section=2, variant='even', block_start=1,
                   block_end=1, source_start=4, source_end=4)
    doc = document(first, empty, inherited)
    assert validate(doc) is doc
    assert len(doc.story_blocks['headers_footers']) == 1
    assert doc.headers_footers == 'head'


def test_json_roundtrip_exact_metadata_and_legacy_omission():
    assert 'auxiliary_stories' not in Document('doc').to_dict()
    doc = document(header(), textbox())
    data = json.loads(json.dumps(doc.to_dict()))
    assert data['auxiliary_stories'] == [asdict(item) for item in doc.auxiliary_stories]
    rebuilt = [AuxiliaryStory(**item) for item in data['auxiliary_stories']]
    assert validate(document(*rebuilt)).to_dict() == doc.to_dict()
    assert list(data['auxiliary_stories'][0]) == list(asdict(header()))


def test_normalization_and_clone_preserve_utf16_metadata_and_independence():
    item = header(source_start=100, source_end=106)
    doc = document(item)
    doc.headers_footers = doc.story_blocks['headers_footers'][0].text = 'e\u0301\r\n\U0001f600'
    before = doc.to_dict()
    normalized = normalize_text(doc, unicode_form='NFC')
    assert normalized.headers_footers == '\u00e9\n\U0001f600'
    assert asdict(normalized.auxiliary_stories[0]) == asdict(item)
    assert doc.to_dict() == before
    copied = clone_model(doc)
    copied.auxiliary_stories[0].source_start = 99
    copied.story_blocks['headers_footers'][0].text = 'changed'
    assert doc.to_dict() == before
    normalized.auxiliary_stories.clear()
    assert doc.auxiliary_stories == [item]


@pytest.mark.parametrize('field', ['ordinal', 'block_start', 'block_end', 'source_start', 'source_end'])
@pytest.mark.parametrize('value', [True, -1, 1.5, '1', None])
def test_invalid_range_types(field, value):
    with pytest.raises(InvalidDocumentError):
        validate(document(header(**{field: value})))


@pytest.mark.parametrize('changes', [
    {'ordinal': 0}, {'source_start': 5}, {'source_end': 0x7fffffff},
    {'block_end': 2}, {'block_start': 1, 'block_end': 0},
    {'story': 'textboxes'}, {'source': 'body'}, {'kind': 'textbox'},
    {'section': 0}, {'section': True}, {'section': None}, {'variant': 'default'},
    {'variant': None}, {'inherited_from': True}, {'inherited_from': 7},
    {'kind': 'footnote_separator', 'variant': 'separator'},
])
def test_invalid_header_metadata(changes):
    with pytest.raises(InvalidDocumentError):
        validate(document(header(**changes)))


@pytest.mark.parametrize('changes', [{'section': 1}, {'variant': 'odd'},
                                     {'inherited_from': 1}, {'kind': 'header'}])
def test_invalid_textbox_identity(changes):
    with pytest.raises(InvalidDocumentError):
        validate(document(textbox(**changes)))


@pytest.mark.parametrize('change', ['format', 'entry', 'missing_story'])
def test_invalid_owner(change):
    doc = document()
    if change == 'format':
        doc.format = 'rtf'
    elif change == 'entry':
        doc.auxiliary_stories = [{}]
    else:
        doc.story_blocks.clear()
    with pytest.raises(InvalidDocumentError):
        validate(doc)


@pytest.mark.parametrize('changes', [{'ordinal': 8}, {'source_start': 3}, {'block_start': 0}])
def test_reject_same_source_overlap_or_duplicate_ordinal(changes):
    later = header(ordinal=14, section=2, source_start=4, source_end=8,
                   block_start=1, block_end=2)
    doc = document(header(), replace(later, **changes))
    doc.story_blocks['headers_footers'].append(Paragraph('next'))
    with pytest.raises(InvalidDocumentError):
        validate(doc)


@pytest.mark.parametrize('changes', [{'inherited_from': 6}, {'variant': 'even'},
    {'kind': 'footer'}, {'section': 1}, {'source_end': 5}, {'block_end': 2}])
def test_invalid_inheritance(changes):
    later = header(ordinal=14, section=2, source_start=4, source_end=4,
                   block_start=1, block_end=1, inherited_from=8)
    doc = document(header(), replace(later, **changes))
    doc.story_blocks['headers_footers'].append(Paragraph('next'))
    with pytest.raises(InvalidDocumentError):
        validate(doc)


def test_reject_stale_inheritance_target():
    doc = document(header(), header(ordinal=14, section=2, block_start=1,
        block_end=2, source_start=4, source_end=8), header(ordinal=20,
        section=3, block_start=2, block_end=2, source_start=8, source_end=8,
        inherited_from=8))
    doc.story_blocks['headers_footers'].append(Paragraph('replacement'))
    with pytest.raises(InvalidDocumentError):
        validate(doc)


def test_inheritance_skips_empty_slots_to_previous_resolved_nonempty():
    doc = document(header(), header(ordinal=14, section=2, block_start=1,
        block_end=1, source_start=4, source_end=4, inherited_from=8),
        header(ordinal=20, section=3, block_start=1, block_end=1,
               source_start=4, source_end=4, inherited_from=8))
    assert validate(doc) is doc


def test_reject_duplicate_section_kind_variant_identity():
    doc = document(header(), header(ordinal=8, block_start=1, block_end=2,
                                    source_start=4, source_end=8))
    doc.story_blocks['headers_footers'].append(Paragraph('duplicate'))
    with pytest.raises(InvalidDocumentError):
        validate(doc)


def test_reject_overlapping_textbox_sources_in_shared_output():
    # Source offsets and ordinal 3 may repeat in different subdocuments;
    # ownership of the shared output block may not.
    doc = document(textbox(), textbox(source='header_textbox'))
    with pytest.raises(InvalidDocumentError):
        validate(doc)


def test_distinct_textbox_sources_allow_independent_cp_and_ordinal():
    doc = document(textbox(), textbox(source='header_textbox', block_start=1, block_end=2))
    doc.story_blocks['textboxes'].append(Paragraph('header box'))
    assert validate(doc) is doc


@pytest.mark.parametrize('item', [textbox(block_end=0),
    textbox(block_end=0, source_end=0), header(block_end=0)])
def test_empty_block_range_requires_empty_header_source_slot(item):
    with pytest.raises(InvalidDocumentError):
        validate(document(item))


def test_auxiliary_record_budget_exact_boundary():
    doc = document(header(), textbox())
    assert validate(doc, max_records=2) is doc
    with pytest.raises(LimitExceededError):
        validate(doc, max_records=1)


@pytest.mark.parametrize('other', ['note', 'comment', 'note_anchor'])
def test_auxiliary_metadata_shares_record_budget(other):
    doc = document(header())
    doc.blocks = [Paragraph('anchor')]
    if other.startswith('note'):
        doc.story_blocks['footnotes'] = [Paragraph('')]
        doc.notes = [Note('footnote', 1, NoteBodyRange('footnotes', 0, 1),
            source_cp=0, anchor_path=['blocks', 0] if other == 'note_anchor' else None)]
    else:
        doc.story_blocks['comment_text'] = [Paragraph('')]
        doc.comments = [Comment(1, CommentBodyRange('comment_text', 0, 1))]
    cost = 4 if other == 'note_anchor' else 2
    assert validate(doc, max_records=cost) is doc
    with pytest.raises(LimitExceededError):
        validate(doc, max_records=cost - 1)


def test_projection_text_budget_counts_both_retained_representations():
    doc = document(header())
    assert validate(doc, max_text_chars=14) is doc
    with pytest.raises(LimitExceededError):
        validate(doc, max_text_chars=13)


@pytest.mark.parametrize('operation', ['to_dict', 'clone', 'normalize'])
def test_auxiliary_metadata_cycles_rejected_without_recursion(operation):
    doc = document()
    doc.auxiliary_stories[0].inherited_from = doc.auxiliary_stories
    with pytest.raises(InvalidDocumentError, match='Cyclic'):
        if operation == 'to_dict':
            doc.to_dict()
        elif operation == 'clone':
            clone_model(doc)
        else:
            normalize_text(doc)


def test_nested_auxiliary_body_depth_budget():
    doc = document(header())
    doc.story_blocks['headers_footers'] = [Table([[Cell(blocks=[Paragraph('')])]])]
    assert validate(doc, max_depth=2) is doc
    with pytest.raises(LimitExceededError):
        validate(doc, max_depth=1)


@pytest.mark.parametrize('source', ['header', 'main_textbox', 'header_textbox'])
def test_source_end_budget_is_inclusive_and_source_relative(source):
    item = (header(source_start=99, source_end=100) if source == 'header'
            else textbox(source=source, source_start=99, source_end=100))
    doc = document(item)
    assert validate(doc, max_text_chars=100) is doc
    assert normalize_text(doc, limits=Limits(max_text_chars=100)).auxiliary_stories == [item]
    with pytest.raises(LimitExceededError, match='source CP'):
        validate(doc, max_text_chars=99)
    with pytest.raises(LimitExceededError, match='source CP'):
        normalize_text(doc, limits=Limits(max_text_chars=99))


def test_empty_header_source_position_still_charged_against_cp_limit():
    doc = document(header(source_start=100, source_end=100, block_end=0))
    assert validate(doc, max_text_chars=100) is doc
    with pytest.raises(LimitExceededError, match='source CP'):
        validate(doc, max_text_chars=99)
