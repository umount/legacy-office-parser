"""Independent selection boundary review; literal UTF-16 CP expectations."""
import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits
from legacy_office_parser.doc import _Budget, _Doc
from test_doc import IN, ROW, definition, mutate, parse
from test_doc_comments import bookmarks, build
from test_doc_fidelity import append_table_part
from test_doc_sections import with_sections


def selected(monkeypatch, main, begin, end, *, props=None, sections=None):
    # Preserve FKP boundaries when replacing a synthetic CR with a section FF.
    source = main.replace('\f', '\r') if sections is not None else main
    data = build(source, tags=[41], props=props)
    if sections is not None:
        mutate(data, 'WordDocument', 1024, main.encode('utf-16le'))
        data = with_sections(data, sections)
    for index, part in bookmarks(len(main.encode('utf-16le')) // 2,
                                 starts=(begin,), ends=(end,)).items():
        append_table_part(data, index, part)
    doc = parse(monkeypatch, data)
    comment = doc.comments[0]
    assert doc.comment_text == 'Body'
    assert comment.anchor_path is not None
    assert comment.source_cp == main.encode('utf-16le').index(b'\x05\0') // 2
    return comment.selection_start, comment.selection_end


@pytest.mark.parametrize('begin,end', [(0, 1), (1, 2), (0, 2), (2, 3), (1, 3),
                                       (0, 3), (3, 4), (2, 4), (0, 4), (1, 4)])
def test_ordinary_empty_paragraph_cr_and_exact_next_start(monkeypatch, begin, end):
    # CPs: A=0, first CR=1, empty-paragraph CR=2, B=3, marker=4, CR=5.
    assert selected(monkeypatch, 'A\r\rB\x05\r', begin, end) == (begin, end)


@pytest.mark.parametrize('begin,end,want', [(0, 2, (0, 2)), (0, 3, (0, 3)),
                                           (2, 3, (2, 3)), (3, 4, (3, 4)),
                                           (4, 5, (4, 5)), (3, 5, (3, 5)),
                                           (0, 5, (0, 5))])
def test_explicit_section_mark_and_empty_following_paragraph(monkeypatch, begin, end, want):
    # A CR FF CR B marker CR. Explicit section begins at CP 3, after FF.
    got = selected(monkeypatch, 'A\r\f\rB\x05\r', begin, end, sections=[0, 3, 7])
    assert got == ((None, None) if want is None else want)


def test_section_sentinel_does_not_create_a_last_paragraph_barrier(monkeypatch):
    assert selected(monkeypatch, 'A\r\rB\x05\r', 0, 4, sections=[0, 100]) == (0, 4)


def test_section_metadata_cannot_relabel_an_ordinary_cr(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='section'):
        selected(monkeypatch, 'A\r\rB\x05\r', 0, 4, sections=[0, 2, 6])


@pytest.mark.parametrize('begin,end,want', [(0, 4, (0, 4)), (1, 3, (1, 3)),
                                           (0, 6, (0, 6)), (4, 5, None),
                                           (5, 6, (5, 6))])
def test_same_cell_paragraphs_and_cell_mark_boundaries(monkeypatch, begin, end, want):
    # First cell A CR CR B CELL; second C marker CELL; TTP CELL.
    main = 'A\r\rB\7C\x05\7\7'
    props = [IN, IN, IN, IN, ROW + definition([0, 0]), b'', b'']
    got = selected(monkeypatch, main, begin, end, props=props)
    assert got == ((None, None) if want is None else want)


@pytest.mark.parametrize('begin,end,want', [(0, 4, (0, 4)), (1, 4, None),
                                           (0, 5, None), (0, 6, (0, 6))])
def test_astral_units_on_both_sides_of_paragraph_boundary(monkeypatch, begin, end, want):
    # First emoji 0..2, CR 2, A 3, second emoji 4..6, marker 6, CR 7.
    got = selected(monkeypatch, '😀\rA😀\x05\r', begin, end)
    assert got == ((None, None) if want is None else want)


def test_new_selection_indexes_are_budgeted_before_reading_paragraphs():
    class UnreadableParagraphs:
        def __len__(self):
            return 20

        def __iter__(self):
            pytest.fail('selection index budget must precede paragraph traversal')

    parser = object.__new__(_Doc)
    parser.budget = _Budget(Limits(max_records=80))
    with pytest.raises(LimitExceededError, match='record'):
        parser._comment_selection_ranges(UnreadableParagraphs())


def test_overlapping_ranges_do_not_rescan_selected_source_units():
    from types import SimpleNamespace

    class CountedSource(bytearray):
        def __init__(self, data):
            super().__init__(data)
            self.reads = 0

        def __getitem__(self, index):
            self.reads += 1
            return super().__getitem__(index)

    count, ranges = 64, 256
    parser = object.__new__(_Doc)
    parser.budget = _Budget(Limits())
    parser.text = CountedSource(('ab\r' * count).encode('utf-16le'))
    parser.section_ends = set()
    parser.comment_selections = {}
    parser._comment_paragraph_known = lambda cp: True
    parser.warn = lambda message: pytest.fail(message)
    props = SimpleNamespace(depth=0, in_table=False, row_end=False,
                            inner_cell=False, inner_ttp=False)
    paragraphs = [(3 * i, 3 * i + 2, 13, 3 * i + 2, props, False, True)
                  for i in range(count)]
    parser.comment_ranges = [SimpleNamespace(source_cp=i, selection_start=0,
                                            selection_end=count * 3 - 1)
                             for i in range(ranges)]
    parser._comment_selection_ranges(paragraphs)
    assert len(parser.comment_selections) == ranges
    # Two byte accesses per scanned unit; bounded endpoint reads per query.
    assert parser.text.reads <= 2 * count * 3 + 4 * ranges


@pytest.mark.parametrize('begin,end,want', [(0, 2, (0, 2)), (0, 5, None),
                                           (3, 5, None), (6, 8, (6, 8)),
                                           (0, 8, None)])
def test_unknown_middle_paragraph_is_checked_without_poisoning_neighbors(begin, end, want):
    from types import SimpleNamespace

    parser = object.__new__(_Doc)
    parser.budget = _Budget(Limits())
    parser.text = 'ab\rcd\ref\r'.encode('utf-16le')
    parser.section_ends = set()
    parser.comment_selections = {}
    parser._comment_paragraph_known = lambda cp: cp != 5
    parser.warn = lambda message: None
    props = SimpleNamespace(depth=0, in_table=False, row_end=False,
                            inner_cell=False, inner_ttp=False)
    paragraphs = [(i, i + 2, 13, i + 2, props, False, True) for i in (0, 3, 6)]
    parser.comment_ranges = [SimpleNamespace(source_cp=8, selection_start=begin, selection_end=end)]
    parser._comment_selection_ranges(paragraphs)
    assert parser.comment_selections.get(8) == want


@pytest.mark.parametrize('depth', [1, 2])
@pytest.mark.parametrize('termination', ['cell', 'row', 'unknown', 'other-region'])
def test_cell_completion_proof_is_explicit_and_region_local(depth, termination):
    from types import SimpleNamespace

    def props(**changes):
        values = dict(depth=depth, in_table=True, row_end=False,
                      inner_cell=False, inner_ttp=False, flags=[], edges=[])
        values.update(changes)
        return SimpleNamespace(**values)

    parser = object.__new__(_Doc)
    parser.budget = _Budget(Limits())
    parser.text = ('A\rB\rC' + ('\7' if depth == 1 else '\r')).encode('utf-16le')
    parser.counts = [len(parser.text) // 2]
    parser.limits = parser.budget.limits
    parser.section_ends = set()
    parser.comment_selections = {}
    parser.warn = lambda message: None
    parser._comment_paragraph_known = lambda cp: not (termination == 'unknown' and cp == 5)
    end_props = props(inner_cell=depth > 1)
    if termination == 'row':
        end_props = props(row_end=depth == 1, inner_ttp=depth > 1)
    elif termination == 'other-region':
        # A terminator at another depth cannot complete the selected region.
        end_props = props(depth=depth + 1, inner_cell=True)
    paragraphs = [(0, 1, 13, 1, props(), False, True),
                  (2, 3, 13, 3, props(), False, True),
                  (4, 5, 7 if depth == 1 else 13, 5, end_props, False, True)]
    parser.comment_ranges = [SimpleNamespace(source_cp=3, selection_start=0, selection_end=3)]
    parser._comment_selection_ranges(paragraphs)
    assert parser.comment_selections.get(3) == ((0, 3) if termination == 'cell' else None)
    assert parser.budget.records == 4 * len(paragraphs) + 1 + (37 if termination == 'row' and depth == 1 else 0)
