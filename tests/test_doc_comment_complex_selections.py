"""Synthetic source CP oracles, independent of projected table coordinates."""
from types import SimpleNamespace

import pytest

from legacy_office_parser import LimitExceededError, Limits
from legacy_office_parser._doc_comments import whole_row_comment_selections
from test_doc import IN, ROW, definition, parse
from test_doc_comment_selections import ranged, selection
from test_doc_nested import cell, paragraph, row


@pytest.mark.parametrize('begin,end,want', [
    (0, 6, (0, 6)), (1, 6, (None, None)), (0, 5, (None, None)),
    (0, 3, (None, None)), (2, 6, (None, None)),
])
def test_two_cells_require_exact_whole_row(monkeypatch, begin, end, want):
    # A=0 CELL=1 B=2 marker=3 CELL=4 TTP=5.
    data = ranged('A\7B\x05\7\7', begin, end,
                  props=[IN, IN, ROW + definition([0, 0]), b'', b''])
    result = parse(monkeypatch, data)
    assert selection(result) == want
    assert result.comment_text == 'Body'
    assert result.comments[0].source_cp == 3
    assert result.comments[0].anchor_path is not None


@pytest.mark.parametrize('begin,end', [(0, 9), (0, 3), (3, 9)])
def test_adjacent_whole_rows_with_different_cell_counts(monkeypatch, begin, end):
    # First row 0..3; second row 3..9, with two cells.
    data = ranged('A\7\7B\7C\x05\7\7', begin, end,
                  props=[IN, ROW + definition([0]), IN, IN,
                         ROW + definition([0, 0]), b'', b''])
    assert selection(parse(monkeypatch, data)) == (begin, end)


def test_complete_outer_row_includes_complete_nested_rows(monkeypatch):
    parts = [paragraph(1, 'P'), cell(2, 'A'), cell(2, 'B'), row(2, (0, 0)),
             cell(1, 'Q'), cell(1, 'R\x05'), row(1, (0, 0))]
    # P CR A CR B CR innerTTP Q CELL R marker CELL outerTTP: 0..13.
    data = ranged(''.join(t for t, _ in parts), 0, 13,
                  props=[p for _, p in parts] + [b'', b''])
    result = parse(monkeypatch, data)
    assert selection(result) == (0, 13)
    assert result.comments[0].source_cp == 10
    assert result.comment_text == 'Body'


def source(*specs):
    """Build raw prepass records; expected ranges remain literal in tests."""
    text = ''
    paragraphs = []
    for body, depth, kind in specs:
        begin = len(text.encode('utf-16le')) // 2
        mark = 7 if depth == 1 and kind in ('cell', 'row') else 13
        end = begin + len(body.encode('utf-16le')) // 2
        props = SimpleNamespace(depth=depth, in_table=bool(depth),
                                row_end=depth == 1 and kind == 'row',
                                inner_cell=depth > 1 and kind == 'cell',
                                inner_ttp=depth > 1 and kind == 'row',
                                flags=[0] if kind == 'row' else [],
                                edges=[0, 100] if kind == 'row' else [])
        paragraphs.append((begin, end, mark, end, props, False, True))
        text += body + chr(mark)
    return text.encode('utf-16le'), paragraphs


def prove(text, paragraphs, **kwargs):
    return whole_row_comment_selections(text, paragraphs, kwargs.pop('sections', set()),
                                       kwargs.pop('known', lambda cp: True),
                                       kwargs.pop('limits', Limits()), **kwargs)


@pytest.mark.parametrize('fault', ['coverage', 'unknown', 'count', 'geometry',
                                  'section', 'field', 'open-cell', 'gap', 'mark'])
def test_uncertain_row_never_publishes_selection(fault):
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'))
    kwargs = {}
    if fault == 'coverage':
        kwargs['known'] = lambda cp: cp != 1
    elif fault == 'unknown':
        paragraphs[0] = (*paragraphs[0][:-1], False)
    elif fault == 'count':
        paragraphs[1][4].flags = [0, 0]
    elif fault == 'geometry':
        paragraphs[1][4].edges = [100, 0]
    elif fault == 'section':
        kwargs['sections'] = {1}
    elif fault == 'field':
        text = '\x13\7\7'.encode('utf-16le')
    elif fault == 'open-cell':
        text, paragraphs = source(('A', 1, 'para'), ('', 1, 'row'))
    elif fault == 'gap':
        paragraphs[0] = (1, *paragraphs[0][1:])
    elif fault == 'mark':
        text = 'A\r\7'.encode('utf-16le')
    assert not prove(text, paragraphs, **kwargs).contains(0, 3)


def test_unclosed_nested_row_cannot_prove_enclosing_row():
    text, paragraphs = source(('P', 1, 'para'), ('A', 2, 'cell'),
                              ('Q', 1, 'cell'), ('', 1, 'row'))
    assert not prove(text, paragraphs).contains(0, 7)


def test_rows_separated_by_ordinary_text_are_not_one_run():
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'),
                              ('B', 0, 'para'), ('C', 1, 'cell'), ('', 1, 'row'))
    result = prove(text, paragraphs)
    assert result.contains(0, 3)
    assert result.contains(5, 8)
    assert not result.contains(0, 8)


def test_record_budget_precedes_traversal():
    class Unreadable:
        def __len__(self):
            return 20

        def __iter__(self):
            pytest.fail('must charge before traversal')

    with pytest.raises(LimitExceededError, match='record'):
        prove(b'', Unreadable(), limits=Limits(max_records=120))


@pytest.mark.parametrize('limit', ['max_depth', 'max_cells', 'max_text_chars'])
def test_resource_limits(limit):
    text, paragraphs = source(('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'),
                              ('Q', 1, 'cell'), ('', 1, 'row'))
    with pytest.raises(LimitExceededError):
        prove(text, paragraphs, limits=Limits(**{limit: 1}))


def test_index_charged_once_and_overlapping_queries_do_not_read_source():
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'))
    charges = []
    result = prove(text, paragraphs, record=charges.append)
    for _ in range(1000):
        assert result.contains(0, 3)
    assert charges == [13]


def test_missing_parent_depth_is_not_invented():
    text, paragraphs = source(('A', 2, 'cell'), ('', 2, 'row'),
                              ('Q', 1, 'cell'), ('', 1, 'row'))
    assert not prove(text, paragraphs).contains(0, 6)


def test_late_incomplete_row_invalidates_pending_table_proof():
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'), ('B', 1, 'para'))
    assert not prove(text, paragraphs).contains(0, 3)


def test_field_outside_table_keeps_existing_conservative_policy():
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'), ('\x13X\x15', 0, 'para'))
    assert not prove(text, paragraphs).contains(0, 3)


def test_hidden_source_text_keeps_literal_cps():
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'))
    paragraphs[0] = (*paragraphs[0][:5], True, True)
    assert prove(text, paragraphs).contains(0, 3)


def test_lone_low_surrogate_cannot_start_a_proven_range():
    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'))
    text = b'\x00\xdc' + text[2:]
    assert not prove(text, paragraphs).contains(0, 3)


def test_aggregate_record_budget_is_charged():
    from legacy_office_parser.doc import _Budget

    text, paragraphs = source(('A', 1, 'cell'), ('', 1, 'row'))
    limits = Limits(max_records=20)
    budget = _Budget(limits)
    budget.record(8)
    with pytest.raises(LimitExceededError, match='record'):
        prove(text, paragraphs, limits=limits, record=budget.record)


def test_decoded_source_uses_character_budget_not_input_stream_byte_budget():
    text, paragraphs = source(('AB', 1, 'cell'), ('', 1, 'row'))
    assert prove(text, paragraphs, limits=Limits(max_stream_bytes=1)).contains(0, 4)
