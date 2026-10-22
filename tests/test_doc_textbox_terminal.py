"""Original synthetic reserved-range sentinels; no corpus-derived bytes."""
import pytest

from legacy_office_parser import InvalidDocumentError, LimitExceededError, Limits
from legacy_office_parser._doc_textboxes import live_textbox_ranges
from test_doc import parse
from test_doc_textboxes import plc
from test_doc_textboxes_integration import textbox_fixture


@pytest.mark.parametrize('terminal', [12, 100, 0x7FFFFFFE])
def test_reserved_terminal_does_not_bound_readable_text(terminal):
    charges = []
    result = live_textbox_ranges(plc([0, 4, 5, 9, terminal], [0, 1, 0, 1]), 10,
                                 Limits(max_text_chars=10), record=charges.append)
    assert result == [(0, 4), (5, 9)]
    assert charges == [4]


@pytest.mark.parametrize('header', [False, True])
def test_full_parser_never_reads_reserved_span(monkeypatch, header):
    data = textbox_fixture('ONE\rTWO\r\r', [0, 4, 8, 100], [0, 0, 1], header)
    result = parse(monkeypatch, data)
    assert result.textboxes == 'ONE\nTWO'
    assert result.text == 'B\n\nONE\nTWO'


def test_reserved_only_never_creates_a_live_range():
    assert live_textbox_ranges(plc([0, 100], [1]), 1, Limits()) == []


@pytest.mark.parametrize('cps,count', [
    ([0, 11, 100], 10), ([11, 100], 10), ([0, 4, 11, 100], 10),
    ([0, 4, 4], 5), ([0, 4, 3], 5), ([0, 4, 0x80000000], 5),
    ([0, 4, 0xFFFFFFFF], 5), ([0, 4, 0x7FFFFFFF], 5),
])
def test_nonfinal_bounds_and_terminal_validity_stay_strict(cps, count):
    with pytest.raises(InvalidDocumentError):
        live_textbox_ranges(plc(cps, [0] * (len(cps) - 1)), count, Limits())


def test_record_budget_precedes_terminal_handling():
    with pytest.raises(LimitExceededError, match='record'):
        live_textbox_ranges(plc([0, 4, 100], [0, 1]), 5, Limits(max_records=1))


def test_live_paragraph_end_check_is_not_bypassed(monkeypatch):
    data = textbox_fixture('BAD!\r', [0, 4, 100], [0, 1])
    with pytest.raises(InvalidDocumentError, match='paragraph mark'):
        parse(monkeypatch, data)


def test_reserved_only_terminal_may_exceed_story():
    assert live_textbox_ranges(plc([0, 3], [0]), 2, Limits()) == []
