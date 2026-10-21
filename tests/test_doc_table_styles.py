"""Original CFB proof and independently authored table-context regressions."""
from pathlib import Path
import hashlib
import json
import struct
import sys

import olefile
import pytest
from legacy_office_parser import parse_doc
from legacy_office_parser import Limits, InvalidDocumentError, LimitExceededError
from legacy_office_parser.doc import _Doc, _Budget, _span, _u16
from legacy_office_parser._doc_styles import Styles
from legacy_office_parser.models import Cell, Paragraph, Table

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'tests/fixtures/doc_table_styles'
MODES = ('visible', 'inherited', 'child_show')
CELLS = [['', 'Value', 'Примечание'], ['alpha beta', '', 'два слова'],
         ['', '42', 'English and русский']]


def streams(path):
    with olefile.OleFileIO(path) as ole:
        return {p[0]: ole.openstream(p).read() for p in ole.listdir()}


def part(data, index):
    off, size = struct.unpack_from('<II', data['WordDocument'], 154 + index * 8)
    return data['1Table'][off:off + size]


def styles(data):
    raw = part(data, 1)
    pos = 2 + struct.unpack_from('<H', raw)[0]
    result = []
    for _ in range(struct.unpack_from('<H', raw, 2)[0]):
        n = struct.unpack_from('<H', raw, pos)[0]
        result.append(raw[pos + 2:pos + 2 + n])
        pos += 2 + n
    assert pos == len(raw)
    return result


@pytest.mark.parametrize('mode', MODES)
def test_generator_is_deterministic(mode):
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        from generate_doc_table_style_fixture import generate
        assert generate(mode) == generate(mode) == (DIR / (mode + '.doc')).read_bytes()
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize('mode', MODES)
def test_wire_style_chain_and_preserved_text(mode):
    data = streams(DIR / (mode + '.doc'))
    source = streams(ROOT / 'tests/fixtures/ordinary_table.doc')
    records = styles(data)
    assert records[:16] == styles(source)
    for index, base, hide in ((16, 0xFFF, None if mode == 'visible' else 1),
                              (17, 16, 0 if mode == 'child_show' else None)):
        raw = records[index]
        assert struct.unpack_from('<H', raw, 2)[0] == base << 4 | 3
        assert struct.unpack_from('<H', raw, 4)[0] & 15 == 3
        assert struct.unpack_from('<H', raw, 6)[0] == len(raw)
        at = 10 + 2 + 2 * (struct.unpack_from('<H', raw, 10)[0] + 1)
        groups = []
        for _ in range(3):
            n = struct.unpack_from('<H', raw, at)[0]
            groups.append(raw[at + 2:at + 2 + n])
            at += 2 + n + (n & 1)
        assert at == len(raw)
        assert groups == [b'', b'', b'' if hide is None else struct.pack('<HB', 0x083C, hide)]
    # Physical text FCs are unchanged; direct CHPX is separate from text storage.
    begin, end = struct.unpack_from('<II', source['WordDocument'], 24)
    assert data['WordDocument'][begin:end] == source['WordDocument'][begin:end]
    assert 'Key'.encode('utf-16le') in data['WordDocument'][begin:end]
    assert set(data['Data']) <= {0}
    plc = part(data, 13)
    count = (len(plc) - 4) // 8
    rows = []
    for i in range(count):
        page = struct.unpack_from('<I', plc, 4 * (count + 1 + i))[0]
        fkp = data['WordDocument'][page * 512:(page + 1) * 512]
        n = fkp[511]
        for j in range(n):
            at = fkp[4 * (n + 1) + 13 * j] * 2
            if not at:
                continue
            size = fkp[at]
            start, length = (at + 1, size * 2 - 1) if size else (at + 2, fkp[at + 1] * 2)
            group = fkp[start + 2:start + length]
            assert b'\x6b\x64' not in group and b'\x46\x66' not in group
            if b'\x08\xd6' in group:
                rows.append(group)
    assert len(rows) == 3
    assert all(g.endswith(b'\x3a\x56\x11\x00') for g in rows)


def expected(cells):
    return [Paragraph('Synthetic document / Синтетический документ'),
            Table([[Cell(t) for t in row] for row in cells]),
            Paragraph('After table / После таблицы')]


@pytest.mark.parametrize('mode', ('visible', 'child_show'))
def test_public_api_visible_controls(mode):
    assert parse_doc(DIR / (mode + '.doc')).blocks == expected(CELLS)


def test_public_api_inherited_hidden_with_direct_show():
    assert parse_doc(DIR / 'inherited.doc').blocks == expected(
        [['', '', ''], ['alpha beta', '', ''], ['', '', '']])


def test_recorded_independent_lo_visibility_comparison():
    report = json.loads((DIR / 'lo-comparison.json').read_text())
    for mode in MODES:
        item = report['files'][mode]
        assert item['sha256'] == hashlib.sha256((DIR / (mode + '.doc')).read_bytes()).hexdigest()
        assert not item['PrintHiddenText']
        assert not item['ShowHiddenCharacters']
        assert not item['ShowHiddenParagraphs']
        assert item['stored_table_text'][0]['A1'] == 'Key'
        assert 'Key' not in item['pdf_visible_text']
        assert 'alpha beta' in item['pdf_visible_text']
    # LO disagrees with the spec oracle: table-style hidden is not applied.
    assert 'Value' in report['files']['inherited']['pdf_visible_text']


def record(index, base=0xFFF, chpx=b'', kind=3):
    groups = {1: (struct.pack('<H', index), chpx),
              2: (chpx,), 3: (b'', b'', chpx)}[kind]
    raw = struct.pack('<5H', 0x1FFE, base << 4 | kind, index << 4 | len(groups), 0, 0)
    raw += struct.pack('<H', 1) + b'S\0\0\0'
    for group in groups:
        raw += struct.pack('<H', len(group)) + group + b'\0' * (len(group) & 1)
    return struct.pack('<H', len(raw)) + raw


def reader(records, limits=None):
    header = struct.pack('<HH', len(records), 10) + b'\0' * 14
    data = struct.pack('<H', len(header)) + header + b''.join(records)
    doc = _Doc.__new__(_Doc)
    doc.limits = limits or Limits()
    doc.budget = _Budget(doc.limits)
    doc.table_part = lambda index: data
    doc.warn = lambda message: None
    return Styles(doc, _span, _u16)


def vanish(value):
    return struct.pack('<HB', 0x083C, value)


@pytest.mark.parametrize('mode,value', [('visible', False), ('inherited', True), ('child_show', False)])
def test_real_fixture_style_resolution(mode, value):
    records = [struct.pack('<H', len(r)) + r for r in styles(streams(DIR / (mode + '.doc')))]
    assert reader(records).table_hidden(17) is value


@pytest.mark.parametrize('operand,result', [(0, False), (1, True), (128, True), (129, False)])
def test_table_parent_and_child_override(operand, result):
    s = reader([record(0, chpx=vanish(1)), record(1, 0, vanish(operand))])
    assert s.table_hidden(1) is result
    assert s.table_hidden(None) is False


def test_same_style_operations_use_parent_not_previous_direct_toggle():
    s = reader([record(0), record(1, 0, vanish(1) + vanish(128))])
    assert s.table_hidden(1) is False


@pytest.mark.parametrize('paragraph,expected_value', [(b'', True), (vanish(0), False), (vanish(1), True)])
def test_paragraph_absence_preserves_base_explicit_false_overrides(paragraph, expected_value):
    s = reader([record(0, chpx=vanish(1)), record(1, kind=1, chpx=paragraph)])
    base = s.table_hidden(0)
    assert s.hidden(1, 1, base) is expected_value
    assert s.hidden(1, 1, False) is bool(paragraph == vanish(1))


def test_conditional_payload_is_not_unconditional_hidden():
    conditional = b'\x85\xca\x05\x01\x00' + vanish(1)
    s = reader([record(0, chpx=conditional)])
    assert s.table_hidden(0) is False


@pytest.mark.parametrize('payload', [b'\x3c\x08', vanish(2), b'\x85\xca\x00',
                                     b'\x85\xca\x05\x01', b'\x16\x24\x01', b'\x55\x08\x01'])
def test_bad_table_chpx(payload):
    with pytest.raises(InvalidDocumentError):
        reader([record(0, chpx=payload)])


@pytest.mark.parametrize('records,message', [
    ([record(0, 1), record(1, 0)], 'cyclic'),
    ([record(0, 7)], 'out of range'),
    ([record(0, 1), b'\0\0'], 'empty'),
    ([record(0, 1), record(1, kind=1)], 'kind'),
])
def test_table_parent_graph_errors(records, message):
    with pytest.raises(InvalidDocumentError, match=message):
        reader(records).table_hidden(0)


def test_normal_table_fallback_and_no_style_distinct():
    records = [b'\0\0'] * 11 + [record(11, chpx=vanish(1))]
    s = reader(records)
    assert s.table_hidden(None) is False
    for index in (-1, 0, 11, 500):
        assert s.table_hidden(index) is True
    assert reader([]).table_hidden(500) is False


def test_table_depth_record_limits_and_cached_calls():
    records = [record(0, chpx=vanish(1))] + [record(i, i-1) for i in range(1, 5)]
    with pytest.raises(LimitExceededError, match='depth'):
        reader(records, Limits(max_depth=4)).table_hidden(4)
    s = reader(records, Limits(max_depth=5))
    assert s.table_hidden(4) is True
    # A cache hit requires no additional traversal/budget. Pin to consumed budget.
    before = vars(s.doc.budget).copy()
    for _ in range(1000):
        assert s.table_hidden(4) is True
    assert vars(s.doc.budget) == before
    with pytest.raises(LimitExceededError, match='record'):
        reader(records, Limits(max_records=20))


def context_streams(text, props, *, records=None, counts=None, prcs=(), prms=None):
    from test_doc import fixture
    from test_doc_styles import stylesheet
    # Normal paragraph, Normal Table hidden, explicit hidden/show table styles.
    records = records or ([record(0, kind=1)] + [b'\0\0'] * 10
                          + [record(11, chpx=vanish(1))] + [b'\0\0'] * 4
                          + [record(16, chpx=vanish(1)), record(17)])
    return stylesheet(fixture([(text, True)], props=props, counts=counts,
                              prcs=prcs, prms=prms), records)


def tistd(index):
    return struct.pack('<HH', 0x563A, index)


@pytest.mark.parametrize('selection,visible', [(None, True), (11, False),
                                               (16, False), (17, True), (500, False)])
def test_applied_style_distinct_from_default_table_identity(monkeypatch, selection, visible):
    from test_doc import IN, ROW, definition, parse
    text = 'outside\rinside\7\7after\r'
    row = ROW + definition([0]) + (b'' if selection is None else tistd(selection))
    doc = parse(monkeypatch, context_streams(text, [b'', IN, row, b'']))
    assert doc.blocks == [Paragraph('outside'), Table([[Cell('inside' if visible else '')]]), Paragraph('after')]


def test_sibling_rows_use_future_ttp_and_distinct_character_cache_context(monkeypatch):
    from test_doc import IN, ROW, definition, parse
    doc = parse(monkeypatch, context_streams('hide\7\7show\7\7hide\7\7',
                [IN, ROW + definition([0]) + tistd(16),
                 IN, ROW + definition([0]) + tistd(17),
                 IN, ROW + definition([0]) + tistd(16)]))
    assert [b.rows[0][0].text for b in doc.blocks] == ['', 'show', '']


@pytest.mark.parametrize('inner_style,expected_inner', [(None, 'inner'), (17, 'inner'), (16, '')])
def test_innermost_row_never_borrows_outer_table_style(monkeypatch, inner_style, expected_inner):
    from test_doc import IN, ROW, definition, parse, sprm, u32
    depth = IN + sprm(0x6649, u32(2))
    inner_ttp = depth + sprm(0x244C, 1) + definition([0])
    if inner_style is not None:
        inner_ttp += tistd(inner_style)
    doc = parse(monkeypatch, context_streams('outer\rinner\r\rrest\7\7',
                [IN, depth + sprm(0x244B, 1), inner_ttp,
                 IN, ROW + definition([0]) + tistd(16)]))
    outer = doc.blocks[0].rows[0][0]
    assert outer.blocks == [Paragraph(''), Table([[Cell(expected_inner)]]), Paragraph('')]


def test_incomplete_row_and_auxiliary_story_do_not_leak_context(monkeypatch):
    from test_doc import IN, ROW, definition, parse
    main = 'hidden\7\7unfinished\7'
    note = 'body\7\7'
    doc = parse(monkeypatch, context_streams(main + note,
                [IN, ROW + definition([0]) + tistd(16), IN, IN, ROW + definition([0])],
                counts=[len(main), len(note), 0, 0, 0, 0, 0]))
    assert 'unfinished' in doc.text and doc.footnotes == 'body'
    assert any('no proven table-style context' in w for w in doc.warnings)


@pytest.mark.parametrize('paragraph,expected_text', [(b'', ''), (vanish(0), 'cell'),
                                                     (vanish(128), ''), (vanish(129), 'cell')])
def test_paragraph_visibility_applies_after_table_base(monkeypatch, paragraph, expected_text):
    from test_doc import IN, ROW, definition, parse
    records = [record(0, kind=1, chpx=paragraph), record(1, chpx=vanish(1))]
    doc = parse(monkeypatch, context_streams('cell\7\7', [IN, ROW + definition([0]) + tistd(1)], records=records))
    assert doc.blocks[0].rows[0][0].text == expected_text


@pytest.mark.parametrize('operations,expected_text', [
    (vanish(0), 'cell'), (vanish(128), ''), (vanish(129), 'cell'),
    (vanish(0) + b'\x33\x2a\x00', ''),
    (vanish(0) + b'\x47\xca\x03' + vanish(0), ''),
])
def test_direct_visibility_and_resets_use_table_based_paragraph(monkeypatch, operations, expected_text):
    from test_doc import IN, ROW, definition, parse
    from test_doc_fidelity import add_chpx
    data = context_streams('cell\7\7', [IN, ROW + definition([0]) + tistd(16)])
    add_chpx(data, [1024, 1030], [operations])
    assert parse(monkeypatch, data).blocks[0].rows[0][0].text == expected_text


def test_character_style_and_piece_override_use_table_base(monkeypatch):
    from test_doc import IN, ROW, definition, parse
    from test_doc_styles import style
    from test_doc_fidelity import add_chpx
    records = [record(0, kind=1), record(1, chpx=vanish(1)), style(2, kind=2, chpx=vanish(0))]
    data = context_streams('cell\7\7', [IN, ROW + definition([0]) + tistd(1)], records=records,
                           prcs=[vanish(128)], prms=[1])
    add_chpx(data, [1024, 1030], [struct.pack('<HH', 0x4A30, 2)])
    # Piece PRM 128 is relative to the selected character style (explicit show).
    assert parse(monkeypatch, data).blocks[0].rows[0][0].text == 'cell'


@pytest.mark.parametrize('external', [False, True])
def test_ttp_style_from_piece_or_external_properties(monkeypatch, external):
    from test_doc import IN, ROW, definition, parse, sprm, u16, u32
    group = ROW + definition([0]) + tistd(16)
    if external:
        data = context_streams('cell\7\7', [IN, sprm(0x6646, u32(0))])
        data['Data'] = u16(len(group)) + group
    else:
        data = context_streams('cell\7\7', [IN, ROW + definition([0])], prcs=[tistd(16)], prms=[1])
    assert parse(monkeypatch, data).blocks[0].rows[0][0].text == ''


def test_note_visibility_uses_table_base_before_filtering(monkeypatch):
    from test_doc import IN, ROW, definition, parse
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc
    main, body = '\x02\7\7', 'note\r\r'
    data = context_streams(main + body, [IN, ROW + definition([0]) + tistd(16), b'', b''],
                           counts=[len(main), len(body), 0, 0, 0, 0, 0])
    add_chpx(data, [1024, 1024 + len(main + body)], [b'\x55\x08\x01'])
    append_table_part(data, 2, reference_plc([0]))
    append_table_part(data, 3, text_plc([0, len(body) - 1]))
    doc = parse(monkeypatch, data)
    assert doc.notes[0].visibility == ['hidden']
    assert doc.notes[0].anchor_path == ['blocks', 0, 'rows', 0, 0]
    assert doc.footnotes == 'note\n'
    assert doc.blocks[0].rows[0][0].text == ''


def test_structural_prepass_cleans_once_and_resolves_style_per_row(monkeypatch):
    from test_doc import IN, ROW, definition, parse
    calls = {'clean': 0, 'table': 0, 'properties': 0}
    original_clean, original_table, original_props = _Doc.clean, Styles.table_hidden, _Doc.properties

    def clean(self, *args, **kwargs):
        calls['clean'] += 1
        return original_clean(self, *args, **kwargs)

    def table(self, *args, **kwargs):
        calls['table'] += 1
        return original_table(self, *args, **kwargs)

    def properties(self, *args, **kwargs):
        calls['properties'] += 1
        return original_props(self, *args, **kwargs)

    monkeypatch.setattr(_Doc, 'clean', clean)
    monkeypatch.setattr(Styles, 'table_hidden', table)
    monkeypatch.setattr(_Doc, 'properties', properties)
    data = context_streams('a' * 2000 + '\7\7', [IN, ROW + definition([0]) + tistd(16)])
    assert parse(monkeypatch, data).blocks[0].rows[0][0].text == ''
    assert calls == {'clean': 2, 'table': 1, 'properties': 6}


def test_prepass_record_and_depth_limits_before_clean(monkeypatch):
    from test_doc import IN, ROW, definition, parse, sprm, u32
    data = context_streams('cell\7\7', [IN, ROW + definition([0]) + tistd(16)])
    original_clean = _Doc.clean
    before = []

    def observe(self, *args, **kwargs):
        before.append(self.budget.records)
        return original_clean(self, *args, **kwargs)

    monkeypatch.setattr(_Doc, 'clean', observe)
    parse(monkeypatch, data)
    threshold = before[0]
    before.clear()
    with pytest.raises(LimitExceededError, match='record'):
        parse(monkeypatch, data, Limits(max_records=threshold - 1))
    assert before == []
    deep = context_streams('cell\r', [IN + sprm(0x6649, u32(3))])
    with pytest.raises(LimitExceededError, match='depth'):
        parse(monkeypatch, deep, Limits(max_depth=2))
    assert before == []


# Literal list independent of the production blacklist, MS-DOC 2.9.336.
@pytest.mark.parametrize('kind', [1, 2, 3])
@pytest.mark.parametrize('opcode,operand', [
    (0x0818, b'\x00'), (0x4A30, b'\x00\x00'),
    (0xCA31, b'\x00'), (0x2A33, b'\x00'), (0xCA47, b'\x00'),
    (0xCA62, b'\x00'), (0x4867, b'\x00\x00'),
    (0x2879, b'\x00'), (0x6887, b'\x00' * 4), (0x4888, b'\x00\x00'),
])
def test_all_explicit_upx_chpx_prohibitions(kind, opcode, operand):
    # Complete wire operands reach the policy check, not a truncation error.
    with pytest.raises(InvalidDocumentError, match='forbidden DOC character style property'):
        reader([record(0, kind=kind, chpx=struct.pack('<H', opcode) + operand)])


@pytest.mark.parametrize('kind', [1, 2])
def test_conditional_character_formatting_remains_forbidden_outside_table(kind):
    with pytest.raises(InvalidDocumentError, match='forbidden DOC character style property'):
        reader([record(0, kind=kind, chpx=b'\x85\xca\x05\x01\x00' + vanish(1))])


@pytest.mark.parametrize('kind', [1, 2, 3])
def test_legal_upx_chpx_vanish_remains_accepted(kind):
    s = reader([record(0, kind=kind, chpx=vanish(1))])
    assert s.hidden(0, kind) is True


def test_selected_table_parent_errors_fail_before_text_cleaning(monkeypatch):
    from test_doc import IN, ROW, definition, parse
    data = context_streams('cell\7\7', [IN, ROW + definition([0]) + tistd(1)],
                           records=[record(0, kind=1), record(1, base=1)])
    cleaned = []
    monkeypatch.setattr(_Doc, 'clean', lambda *args, **kwargs: cleaned.append(True))
    with pytest.raises(InvalidDocumentError, match='cyclic'):
        parse(monkeypatch, data)
    assert cleaned == []


def test_incomplete_row_note_is_explicitly_unknown(monkeypatch):
    from test_doc import IN, parse
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc
    main, body = '\x02\7', 'note\r\r'
    data = context_streams(main + body, [IN + tistd(16), b'', b''],
                           counts=[len(main), len(body), 0, 0, 0, 0, 0])
    add_chpx(data, [1024, 1024 + len(main + body)], [b'\x55\x08\x01'])
    append_table_part(data, 2, reference_plc([0]))
    append_table_part(data, 3, text_plc([0, len(body) - 1]))
    doc = parse(monkeypatch, data)
    assert doc.notes[0].visibility == ['unknown']
    assert doc.notes[0].anchor_path == ['blocks', 0, 'rows', 0, 0]
