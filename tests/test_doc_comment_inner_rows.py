"""Exact single depth-two row bookmarks; original source/PLC expectations."""
import struct

import pytest

from legacy_office_parser import Limits, LimitExceededError, normalize_text
from legacy_office_parser._doc_comments import whole_row_comment_selections
from legacy_office_parser.doc import _Budget
from test_doc import parse
from test_doc_comment_selections import ranged, selection
from test_doc_comment_complex_selections import source
from test_doc_nested import cell, paragraph, row


def transport(parts, begin, end):
    return ranged(''.join(t for t, _ in parts), begin, end,
                  props=[p for _, p in parts] + [b'', b''])


def parts():
    # P CR | A innerCELL B ref innerCELL innerTTP | Q outerCELL outerTTP
    return [paragraph(1, 'P'), cell(2, 'A'), cell(2, 'B\x05'),
            row(2, (0, 0)), cell(1, 'Q'), row(1)]


@pytest.mark.parametrize('begin,end,want', [
    (2, 8, (2, 8)), (3, 8, (None, None)), (2, 7, (None, None)),
    (2, 6, (None, None)), (4, 8, (None, None)), (0, 8, (None, None)),
    (2, 10, (None, None)), (0, 11, (0, 11)),
])
def test_literal_transport_endpoints_and_unchanged_ownership(monkeypatch, begin, end, want):
    data = transport(parts(), begin, end)
    def raw(index):
        at, size = struct.unpack_from('<II', data['WordDocument'], 154 + index * 8)
        return data['1Table'][at:at + size]
    start, sentinel, ibkl, bkc = struct.unpack('<IIHH', raw(42))
    limit = struct.unpack_from('<I', raw(43), ibkl * 4)[0]
    assert (start, limit, sentinel, bkc) == (begin, end, 12, 0)
    d = parse(monkeypatch, data)
    assert selection(d) == want
    assert d.comment_text == 'Body' and d.text.count('Body') == 1
    c = d.comments[0]
    assert c.source_cp == 5
    assert c.anchor_path == ['blocks', 0, 'rows', 0, 0, 'blocks', 1, 'rows', 0, 1]
    assert c.body.block_start == 0 and c.body.block_end == 1
    assert normalize_text(d).comments == d.comments
    assert d.to_dict()['comments'][0]['selection_start'] == want[0]


def index(specs=None, **kwargs):
    text, ps = source(*(specs or [('P', 1, 'para'), ('A', 2, 'cell'),
                         ('', 2, 'row'), ('Q', 1, 'cell'), ('', 1, 'row')]))
    return text, ps


def prove(text, ps, **kwargs):
    return whole_row_comment_selections(text, ps, kwargs.pop('sections', set()),
        kwargs.pop('known', lambda cp: True), kwargs.pop('limits', Limits()),
        include_inner=True, **kwargs)


def test_default_helper_does_not_expand_its_scope():
    text, ps = index()
    assert not whole_row_comment_selections(text, ps, set(), lambda cp: True, Limits()).contains(2, 5)
    assert prove(text, ps).contains(2, 5)


@pytest.mark.parametrize('fault', ['inner-count', 'outer-count', 'inner-edges', 'outer-edges',
    'unknown-parent', 'unknown-cell', 'unknown-inner-row', 'unknown-outer-row',
    'inner-cell-flag', 'inner-row-flag', 'outer-open', 'missing-parent',
    'section', 'field-outside', 'wrong-source-mark', 'gap', 'later-open-row'])
def test_unproven_inner_or_enclosing_structure_refuses(fault):
    text, ps = index()
    kwargs = {}
    if fault in ('inner-count', 'outer-count'):
        ps[2 if fault.startswith('inner') else 4][4].flags = [0, 0]
    elif fault in ('inner-edges', 'outer-edges'):
        ps[2 if fault.startswith('inner') else 4][4].edges = [100, 0]
    elif fault.startswith('unknown'):
        which = {'unknown-parent': 0, 'unknown-cell': 1, 'unknown-inner-row': 2,
                 'unknown-outer-row': 4}[fault]
        kwargs['known'] = lambda cp: cp != ps[which][3]
    elif fault == 'inner-cell-flag':
        ps[1][4].inner_cell = False
    elif fault == 'inner-row-flag':
        ps[2][4].inner_ttp = False
    elif fault == 'outer-open':
        text, ps = index([('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'),
                          ('Q', 1, 'para'), ('', 1, 'row')])
    elif fault == 'missing-parent':
        ps[0][4].depth = 2
    elif fault == 'section':
        kwargs['sections'] = {ps[3][3]}
    elif fault == 'field-outside':
        text, ps = index([('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'),
                          ('Q', 1, 'cell'), ('', 1, 'row'), ('\x13X\x15', 0, 'para')])
    elif fault == 'wrong-source-mark':
        text = text[:8] + b'\x07\0' + text[10:]
    elif fault == 'gap':
        ps[1] = (3, *ps[1][1:])
    elif fault == 'later-open-row':
        text, ps = index([('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'),
                          ('Q', 1, 'cell'), ('', 1, 'row'), ('Broken', 1, 'para')])
    assert not prove(text, ps, **kwargs).contains(2, 5)


def test_two_inner_rows_remain_individual_not_a_new_row_run():
    text, ps = index([('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'),
                      ('B', 2, 'cell'), ('', 2, 'row'), ('Q', 1, 'cell'), ('', 1, 'row')])
    got = prove(text, ps)
    assert got.contains(2, 5) and got.contains(5, 8)
    assert not got.contains(2, 8)


def test_equal_depth_in_different_outer_cells_is_not_shared_ownership():
    text, ps = index([('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'), ('Q', 1, 'cell'),
                      ('R', 1, 'para'), ('B', 2, 'cell'), ('', 2, 'row'), ('S', 1, 'cell'), ('', 1, 'row')])
    ps[-1][4].flags = [0, 0]
    ps[-1][4].edges = [0, 100, 200]
    got = prove(text, ps)
    assert got.contains(2, 5) and got.contains(9, 12)
    assert not got.contains(2, 12)


def test_deeper_row_and_depth_two_row_containing_it_remain_unsupported():
    text, ps = index([('P', 1, 'para'), ('M', 2, 'para'), ('D', 3, 'cell'), ('', 3, 'row'),
                      ('N', 2, 'cell'), ('', 2, 'row'), ('Q', 1, 'cell'), ('', 1, 'row')])
    got = prove(text, ps)
    assert not got.contains(4, 7)
    assert not got.contains(2, 10)
    assert got.contains(0, 13)  # Existing fully closed outer row proof.


def test_deeper_previous_row_does_not_poison_plain_following_inner_row():
    text, ps = index([('P', 1, 'para'), ('M', 2, 'para'), ('D', 3, 'cell'), ('', 3, 'row'),
                      ('N', 2, 'cell'), ('', 2, 'row'), ('A', 2, 'cell'), ('', 2, 'row'),
                      ('Q', 1, 'cell'), ('', 1, 'row')])
    got = prove(text, ps)
    assert not got.contains(2, 10)
    assert got.contains(10, 13)


def test_hidden_and_astral_source_offsets_are_not_output_offsets(monkeypatch):
    body = [paragraph(1, '😀'), cell(2, '🚀\x05'), row(2), cell(1, 'Q'), row(1)]
    d = parse(monkeypatch, transport(body, 3, 8))
    assert selection(d) == (3, 8) and d.comments[0].source_cp == 5
    text, ps = index()
    ps[1] = (*ps[1][:5], True, True)
    assert prove(text, ps).contains(2, 5)
    text = text[:4] + b'\0\xdc' + text[6:]
    assert not prove(text, ps).contains(2, 5)


@pytest.mark.parametrize('limit', ['max_depth', 'max_cells', 'max_text_chars'])
def test_existing_resource_guards(limit):
    text, ps = index()
    with pytest.raises(LimitExceededError):
        prove(text, ps, limits=Limits(**{limit: 1}))


def test_precharge_aggregate_and_repeated_queries():
    text, ps = index()
    charges = []
    got = prove(text, ps, limits=Limits(max_records=46), record=charges.append)
    assert charges == [46]  # (6+3)*5 + 1
    ps.clear()
    for _ in range(1000):
        assert got.contains(2, 5)
    class Unreadable:
        def __len__(self):
            return 5
        def __iter__(self):
            pytest.fail('must fail before traversal')
    with pytest.raises(LimitExceededError):
        prove(text, Unreadable(), limits=Limits(max_records=45))
    budget = _Budget(Limits(max_records=50))
    budget.record(5)
    with pytest.raises(LimitExceededError):
        prove(text, Unreadable(), limits=budget.limits, record=budget.record)


def test_row_after_a_section_is_not_joined_to_earlier_content():
    text, ps = index([('Before', 0, 'para'), ('P', 1, 'para'), ('A', 2, 'cell'),
                      ('', 2, 'row'), ('Q', 1, 'cell'), ('', 1, 'row')])
    got = prove(text, ps, sections={6}, include_ordinary=True)
    assert got.contains(9, 12)
    assert not got.contains(0, 12)


def test_invalid_later_table_does_not_erase_previously_closed_inner_row():
    text, ps = index([('P', 1, 'para'), ('A', 2, 'cell'), ('', 2, 'row'),
                      ('Q', 1, 'cell'), ('', 1, 'row'), ('Between', 0, 'para'),
                      ('R', 1, 'para'), ('B', 2, 'cell'), ('', 2, 'row'), ('Broken', 1, 'para')])
    got = prove(text, ps)
    assert got.contains(2, 5)
    assert got.inner_rows == {(2, 5)}


def test_transport_builds_inner_index_once_and_only_when_present(monkeypatch):
    import legacy_office_parser._doc_comments as comments
    original = comments.whole_row_comment_selections
    calls = []
    def capture(*args, **kwargs):
        calls.append(kwargs['include_inner'])
        return original(*args, **kwargs)
    monkeypatch.setattr(comments, 'whole_row_comment_selections', capture)
    d = parse(monkeypatch, transport(parts(), 2, 8))
    assert selection(d) == (2, 8) and calls == [True]
    calls.clear()
    d = parse(monkeypatch, transport([cell(1, 'A\x05'), row(1)], 0, 4))
    assert selection(d) == (0, 4) and calls == [False]
