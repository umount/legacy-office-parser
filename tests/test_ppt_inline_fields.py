"""Original inline-field wire fixtures; no computed date or Office rendering oracle."""
from dataclasses import replace
from pathlib import Path
from struct import pack, pack_into

import pytest

from legacy_office_parser import ppt
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import atom, container, persist, run, text
from test_ppt_fields import fixture, hf, slide
from test_ppt_master_text import drawing, shape


def marker(position, typ=4090, version=0, instance=0):
    tail = bytes(128) if typ == 4117 else (bytes(4) if typ == 4087 else b'')
    return atom(typ, pack('<I', position) + tail, version, instance)


def inline(raw):
    return drawing(container(0xf004, atom(0xf00d, raw)))


def case(raw, footer='Finance Team', flags=32, **kwargs):
    return fixture(local=hf(flags, footer, None), slide_payload=inline(raw), **kwargs)


@pytest.mark.parametrize('unicode', [True, False])
def test_enabled_local_footer_in_own_text_and_no_supplement(monkeypatch, unicode):
    result = run(monkeypatch, case(text('Owner: *', unicode=unicode) + marker(7)))
    assert result.text == 'Owner: Finance Team'
    assert result.warnings == []


@pytest.mark.parametrize('raw,positions,expected', [
    ('  😀\r\nOwner: *  ', [13], '😀\nOwner: Finance Team'),
    ('* / *', [4, 0], 'Finance Team / Finance Team'),
    ('**', [0, 1], 'Finance TeamFinance Team'),
    ('*', [0], 'Finance Team'),
])
def test_original_utf16_units_and_unordered_positions(monkeypatch, raw, positions, expected):
    result = run(monkeypatch, case(text(raw) + b''.join(marker(p) for p in positions)))
    assert result.text == expected
    assert result.warnings == []


def test_footer_whitespace_normalized_after_substitution(monkeypatch):
    result = run(monkeypatch, case(text('A*B') + marker(1), footer=' x\r\ny '))
    assert result.text == 'A x\ny B'


def test_multiple_headers_do_not_share_positions(monkeypatch):
    raw = text('A*') + marker(1) + text('B*') + marker(1)
    assert run(monkeypatch, case(raw)).text == 'AFinance Team\nBFinance Team'


def test_marker_can_precede_its_text_atom(monkeypatch):
    raw = atom(3999, pack('<I', 1)) + marker(0) + atom(4000, '*'.encode('utf-16le'))
    assert run(monkeypatch, case(raw)).text == 'Finance Team'


def test_equal_ordinary_body_is_preserved(monkeypatch):
    f = fixture(local=hf(32, 'same', None), slide_payload=drawing(shape('same')) + inline(text('*') + marker(0)))
    assert run(monkeypatch, f).text == 'same\nsame'


@pytest.mark.parametrize('raw', [
    text('**') + marker(0) + marker(1, 4056),
    text('**') + marker(0) + marker(1, 4117),
    text('*') + marker(0) + atom(0x7777),
    text('*') + atom(4000, 'x'.encode('utf-16le')) + marker(0),
    text('not a marker') + marker(0),
])
def test_mixed_unknown_or_ambiguous_text_warns_without_guessing(monkeypatch, raw):
    result = run(monkeypatch, case(raw))
    assert 'Finance Team' not in result.text
    assert any('field markers are not evaluated' in w for w in result.warnings)


@pytest.mark.parametrize('settings', [None, hf(0, 'Hidden'), hf(32, None)])
def test_missing_or_disabled_local_source_does_not_borrow_default(monkeypatch, settings):
    f = fixture(local=settings, default=hf(32, 'Default', instance=3), slide_payload=inline(text('*') + marker(0)))
    result = run(monkeypatch, f)
    assert result.text == '*'
    assert any('field markers are not evaluated' in w for w in result.warnings)


def test_empty_explicit_footer_replaces_marker(monkeypatch):
    result = run(monkeypatch, case(text('A*B') + marker(1), footer=''))
    assert result.text == 'AB'
    assert result.warnings == []


@pytest.mark.parametrize('raw', [
    text('*') + marker(0) + marker(0),
    text('*') + marker(0) + marker(0, 4117),
    text('*') + marker(1), text('*') + marker(0xffffffff),
    marker(0) + text('*'),
    text('previous') + text('') + marker(0),
    text('*') + marker(0, version=1), text('*') + marker(0, instance=1),
])
def test_invalid_positions_headers_and_duplicate_markers_fail(monkeypatch, raw):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, case(raw))


@pytest.mark.parametrize('payload,version,instance', [
    (b'', 0, 0), (bytes(131), 0, 0), (bytes(133), 0, 0),
    (bytes(132), 1, 0), (bytes(132), 0, 1),
    (pack('<I', 1) + bytes(128), 0, 0),
])
def test_rtf_datetime_validation(monkeypatch, payload, version, instance):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, case(text('*') + atom(4117, payload, version, instance)))


def test_rtf_datetime_stays_literal_and_warns(monkeypatch):
    raw = text('Date: *') + atom(4117, pack('<I', 6) + 'yyyy-MM-dd'.encode('utf-16le').ljust(128, b'\0'))
    result = run(monkeypatch, fixture(slide_payload=inline(raw)))
    assert result.text == 'Date: *'
    assert any('field markers are not evaluated' in w for w in result.warnings)


def test_replacement_budget_checked_before_footer_decode(monkeypatch):
    f = case(text('**') + marker(0) + marker(1), footer='x' * 100)
    decoded = []
    original = ppt._Parser.decode

    def observe(self, rec, *args, **kwargs):
        if rec.end - rec.start == 200:
            decoded.append(rec)
        return original(self, rec, *args, **kwargs)

    monkeypatch.setattr(ppt._Parser, 'decode', observe)
    with pytest.raises(LimitExceededError, match='inline field text'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=201))
    assert decoded == []
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=202)).text == 'x' * 200


def test_repeated_slides_charge_each_replacement(monkeypatch):
    f = case(text('*') + marker(0), footer='abc', count=2)
    with pytest.raises(LimitExceededError):
        run(monkeypatch, f, replace(Limits(), max_text_chars=7))
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=8)).text == 'abc\n\nabc'


def test_next_slide_cannot_reuse_previous_local_footer(monkeypatch):
    f = case(text('*') + marker(0))
    f.edit({1: container(1000, container(4080, persist(10, 200) + persist(11, 201))),
            10: slide(inline(text('*') + marker(0)) + hf(32, 'first'), master=0, objects=False),
            11: slide(inline(text('*') + marker(0)), master=0, objects=False)})
    assert [s.text for s in run(monkeypatch, f).slides] == ['first', '*']


def complete_cfb(file):
    """Minimal authored CFB v3: two regular streams, FAT and directory, no mini-FAT."""
    end, free = 0xfffffffe, 0xffffffff
    streams = [('Current User', file.current()), ('PowerPoint Document', bytes(file.data))]
    assert all(len(data) <= 4096 for _, data in streams)
    header = bytearray(512)
    header[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    pack_into('<HHHHH', header, 24, 0x3e, 3, 0xfffe, 9, 6)
    pack_into('<9I', header, 40, 0, 1, 0, 0, 4096, end, 0, end, 0)
    pack_into('<109I', header, 76, 1, *([free] * 108))
    directory = bytearray(512)

    def entry(index, name, typ, start, size, child=free, right=free):
        offset = index * 128
        label = (name + '\0').encode('utf-16le')
        directory[offset:offset + len(label)] = label
        pack_into('<HBBIII', directory, offset + 64, len(label), typ, 0 if index == 2 else 1, free, right, child)
        pack_into('<IQ', directory, offset + 116, start, size)

    entry(0, 'Root Entry', 5, end, 0, child=1)
    entry(1, streams[0][0], 2, 2, 4096, right=2)
    entry(2, streams[1][0], 2, 10, 4096)
    fat = [end, 0xfffffffd] + list(range(3, 10)) + [end] + list(range(11, 18)) + [end]
    return bytes(header + directory) + pack('<128I', *(fat + [free] * (128 - len(fat)))) + b''.join(
        data.ljust(4096, b'\0') for _, data in streams)


def test_original_complete_cfb_through_real_ole_reader():
    f = case(text('Owner: *') + marker(7))
    data = (Path(__file__).parent / 'fixtures/ppt_inline_fields/static_footer.ppt').read_bytes()
    assert data == complete_cfb(f)
    result = ppt.parse_ppt_bytes(data, Limits())
    assert result.text == 'Owner: Finance Team'
    assert result.warnings == []


@pytest.mark.parametrize('position', [0, 1])
def test_surrogate_pair_is_never_split_or_replaced(monkeypatch, position):
    result = run(monkeypatch, case(text('😀*') + marker(position)))
    assert result.text == '😀*'
    assert any('field markers are not evaluated' in w for w in result.warnings)


def test_only_target_header_is_blocked_by_mixed_fields(monkeypatch):
    raw = text('**') + marker(0) + marker(1, 4056) + text('Owner: *') + marker(7)
    result = run(monkeypatch, case(raw))
    assert result.text == '**\nOwner: Finance Team'
    assert any('field markers are not evaluated' in w for w in result.warnings)


@pytest.mark.parametrize('outline', [False, True])
@pytest.mark.parametrize('geometry', ['Owner: *', 'Owner: Finance Team', 'Distinct art'])
@pytest.mark.parametrize('reverse', [False, True])
def test_expansion_keeps_original_same_shape_geometry_equivalence(monkeypatch, outline, geometry, reverse):
    from test_ppt import File, document
    from test_ppt_wordart import wordart

    raw = text('Owner: *') + marker(7)
    native = atom(0xf00d, atom(3998, pack('<I', 0)) if outline else raw)
    art = wordart(geometry)
    local_shape = container(0xf004, art + native if reverse else native + art)
    # The same original text on an unrelated geometry-only shape is independent.
    other_shape = container(0xf004, wordart('Owner: *'))
    f = File().edit({
        1: document(persist(2, 200) + (raw if outline else b'')),
        2: slide(drawing(local_shape + other_shape) + hf(32, 'Finance Team', None),
                 master=0, objects=False),
    })
    result = run(monkeypatch, f)
    expected = 'Owner: Finance Team\n'
    if geometry == 'Distinct art':
        expected += 'Distinct art\n'
    assert result.text == expected + 'Owner: *'
    assert result.warnings == []


def test_outline_original_equivalence_is_specific_to_referenced_block(monkeypatch):
    from test_ppt import File, document
    from test_ppt_wordart import wordart

    raw = text('First: *') + marker(7) + text('Second: *') + marker(8)
    # The shape references the second block, so first-block geometry must survive.
    own_shape = container(0xf004, wordart('First: *') + atom(0xf00d, atom(3998, pack('<I', 1))))
    f = File().edit({1: document(persist(2, 200) + raw),
                     2: slide(drawing(own_shape) + hf(32, 'Team', None), master=0, objects=False)})
    result = run(monkeypatch, f)
    assert result.text == 'First: Team\nSecond: Team\nFirst: *'
    assert result.warnings == []
