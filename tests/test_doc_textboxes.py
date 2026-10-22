"""Synthetic textbox PLCs only; no documents or private corpus contents.

Integration: select pair 56 for counts[5], pair 58 for counts[6], call
live_textbox_ranges with record=self.budget.record, and walk each returned
range at the corresponding subdocument base. Reset fields per live range.
Missing nonempty PLCs retain the full story with warn=self.warn; present
invalid PLCs raise without fallback.
"""
import struct

import pytest

from legacy_office_parser._doc_textboxes import (
    PLCF_HDR_TXBX_TXT, PLCF_TXBX_TXT, live_textbox_ranges,
)
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits


def plc(cps, flags, lids=None):
    assert len(cps) == len(flags) + 1
    records = []
    for flag, lid in zip(flags, lids or [0] * len(flags)):
        record = bytearray(22)
        struct.pack_into('<H', record, 8, flag)
        struct.pack_into('<I', record, 14, lid)
        records.append(record)
    return struct.pack('<' + 'I' * len(cps), *cps) + b''.join(records)


def ranges(data, count, **kwargs):
    return live_textbox_ranges(data, count, Limits(), **kwargs)


def test_main_and_header_pair_indexes():
    assert (PLCF_TXBX_TXT, PLCF_HDR_TXBX_TXT) == (56, 58)


@pytest.mark.parametrize('flag', [0, 1, 2, 0xFFFF])
def test_last_record_always_reserved_regardless_of_flag_lid_or_length(flag):
    text = 'LIVE\rOLD\r'
    result = ranges(plc([0, 5, 9], [0, flag], [42, 999]), len(text))
    assert result == [(0, 5)]
    assert ''.join(text[a:b] for a, b in result) == 'LIVE\r'


@pytest.mark.parametrize('flag', [1, 3, 0x8001, 0xFFFF])
def test_intermediate_reusable_record_skipped_and_other_flag_bits_ignored(flag):
    assert ranges(plc([0, 3, 4, 7, 11], [0, flag, 0, 0]), 11) == [(0, 3), (4, 7)]


def test_only_reserved_record_is_empty_even_with_nonempty_story():
    assert ranges(plc([0, 10], [0]), 10) == []


def test_all_reusable_records_produce_no_live_ranges():
    assert ranges(plc([0, 1, 2, 7], [1, 3, 0]), 7) == []


def test_absent_plc_empty_story_does_not_warn():
    messages = []
    assert ranges(b'', 0, warn=messages.append) == []
    assert messages == []


def test_absent_plc_preserves_full_story_with_document_warning():
    messages = []
    assert ranges(b'', 9, warn=messages.append) == [(0, 9)]
    assert len(messages) == 1
    assert 'active ranges cannot be verified' in messages[0]
    assert 'reserved text' in messages[0]


def test_absent_plc_without_warning_callback_emits_user_warning():
    with pytest.warns(UserWarning, match='active ranges cannot be verified'):
        assert ranges(b'', 9) == [(0, 9)]


@pytest.mark.parametrize('data', [b'\0', b'\0' * 3, b'\0' * 4, b'\0' * 29,
                                  b'\0' * 31, plc([0, 2, 3], [0, 0]) + b'x'])
def test_invalid_sizes(data):
    with pytest.raises(InvalidDocumentError):
        ranges(data, 10)


@pytest.mark.parametrize('cps,count', [([0, 0], 1), ([2, 1], 2),
                                      ([0, 0xFFFFFFFF], 10), ([11, 12], 10),
                                      ([0, 3, 2], 3), ([0, 3, 3], 3)])
def test_invalid_boundaries_including_reserved_range(cps, count):
    with pytest.raises(InvalidDocumentError):
        ranges(plc(cps, [0] * (len(cps) - 1)), count)


@pytest.mark.parametrize('count', [-1, 0x80000000, 0xFFFFFFFF])
def test_invalid_signed_story_length(count):
    with pytest.raises(InvalidDocumentError):
        ranges(b'', count)


@pytest.mark.parametrize('flag', [2, 0x8000])
def test_invalid_nonfinal_reusable_flag(flag):
    with pytest.raises(InvalidDocumentError, match='flag'):
        ranges(plc([0, 1, 2], [flag, 0]), 2)


def test_nonfinal_live_range_must_exceed_one_cp():
    with pytest.raises(InvalidDocumentError, match='live textbox range'):
        ranges(plc([0, 1, 2], [0, 0]), 2)


def test_nonfinal_reusable_range_must_be_one_cp():
    with pytest.raises(InvalidDocumentError, match='reusable textbox range'):
        ranges(plc([0, 2, 3], [1, 0]), 3)


def test_relative_ranges_are_not_rebased_or_extended():
    assert ranges(memoryview(plc([2, 5, 6], [0, 0])), 9) == [(2, 5)]


def test_record_budget_includes_reserved_entries():
    charges = []
    assert ranges(plc([0, 3, 4, 7, 8], [0, 1, 0, 0]), 8,
                  record=charges.append) == [(0, 3), (4, 7)]
    assert charges == [4]


def test_shared_budget_can_reject_second_plc():
    remaining = 3

    def record(n):
        nonlocal remaining
        remaining -= n
        if remaining < 0:
            raise LimitExceededError('shared record budget')

    data = plc([0, 2, 3], [0, 0])
    assert ranges(data, 3, record=record) == [(0, 2)]
    with pytest.raises(LimitExceededError, match='shared'):
        ranges(data, 3, record=record)


def test_per_plc_record_limit_checked_before_callback():
    calls = []
    with pytest.raises(LimitExceededError, match='record'):
        live_textbox_ranges(plc([0, 2, 3], [0, 0]), 3, Limits(max_records=1),
                            record=calls.append)
    assert calls == []


def test_text_limit_counts_reserved_text_too():
    with pytest.raises(LimitExceededError, match='text'):
        live_textbox_ranges(plc([0, 100], [0]), 100, Limits(max_text_chars=99))


def test_plc_byte_limit():
    with pytest.raises(LimitExceededError, match='size limit'):
        live_textbox_ranges(plc([0, 1], [0]), 1, Limits(max_stream_bytes=29))


def test_over_ten_thousand_records_keeps_correct_data_offset():
    n = 10_001
    cps = list(range(0, 2 * n + 1, 2))
    result = live_textbox_ranges(plc(cps, [0] * n), cps[-1], Limits(max_records=n))
    assert len(result) == n - 1
    assert result[0] == (0, 2)
    assert result[-1] == (2 * (n - 2), 2 * (n - 1))


def test_each_truncated_prefix_is_a_structured_error():
    data = plc([0, 3, 4, 7, 8], [0, 1, 0, 0])
    # Structurally complete shorter PLCs can arise from truncation; they still
    # must either parse safely or raise a documented parser error.
    for end in range(len(data)):
        try:
            result = ranges(data[:end], 8, warn=lambda message: None)
        except InvalidDocumentError:
            continue
        assert all(0 <= a < b <= 8 for a, b in result)


@pytest.mark.parametrize('story_index,pair_index', [(5, PLCF_TXBX_TXT),
                                                  (6, PLCF_HDR_TXBX_TXT)])
def test_main_and_header_plcs_from_synthetic_fib(story_index, pair_index):
    from test_doc import fixture, mutate, u32

    # Every preceding subdocument is nonempty, exercising relative CPs at
    # different absolute bases without depending on doc.py integration.
    stories = ['B\r', 'F\r', 'H\r', 'C\r', 'E\r', 'T\r', 'U\r']
    stories[story_index] = 'LIVE\rOLD\r'
    counts = list(map(len, stories))
    streams = fixture([(''.join(stories), True)], counts=counts)
    data = plc([0, 5, 9], [0, 0], [42, 0])
    offset = len(streams['1Table'])
    streams['1Table'] += data
    mutate(streams, 'WordDocument', 154 + pair_index * 8, u32(offset) + u32(len(data)))
    fc, lcb = struct.unpack_from('<II', streams['WordDocument'], 154 + pair_index * 8)
    result = ranges(memoryview(streams['1Table'])[fc:fc + lcb], counts[story_index])
    base = sum(counts[:story_index])
    text = ''.join(stories)
    assert ''.join(text[base + a:base + b] for a, b in result) == 'LIVE\r'


def test_present_malformed_plc_never_falls_back_or_warns():
    messages = []
    with pytest.raises(InvalidDocumentError):
        ranges(b'broken', 9, warn=messages.append)
    assert messages == []


def test_absent_plc_still_enforces_text_limit_before_warning():
    messages = []
    with pytest.raises(LimitExceededError):
        live_textbox_ranges(b'', 10, Limits(max_text_chars=9), warn=messages.append)
    assert messages == []
