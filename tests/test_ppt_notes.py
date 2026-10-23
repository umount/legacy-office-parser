"""Authored notes-master records; independent helper and ownership checks."""
from dataclasses import replace
from struct import pack

import pytest

from legacy_office_parser._ppt_notes import notes_master
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.ppt import _Parser
from test_ppt import atom, container, text
from test_ppt_master_text import drawing, shape


def master(shapes=b'', backlink=0, flags=0, extra=b''):
    return container(1008, atom(1009, pack('<IHH', backlink, flags, 0), 1)
                     + drawing(shapes) + extra)


def parser(raw, limits=Limits(), pid=7):
    result = _Parser(raw, limits)
    result.persist = {7: 0}
    result.notes_master_id = pid
    result.notes_master_cache = None
    return result


def test_ordinary_artwork_only_and_cache():
    hidden = atom(0xf00b, pack('<HI', 0x3bf, 0x20002), 3, 1)
    shapes = shape('Привет 世界 😀', kind=0) + shape('same') * 2
    shapes += b''.join(shape('PROMPT', placeholder=i) for i in range(1, 27))
    shapes += shape('DELETED', flags=8) + shape('HIDDEN', extra=hidden)
    shapes += container(0xf003, shape('', flags=1, extra=hidden) + shape('CHILD'))
    p = parser(master(shapes))
    blocks, fields = notes_master(p)
    assert blocks == [(1, 'Привет 世界 😀'), (1, 'same'), (1, 'same')]
    assert fields == {7, 8, 9, 10}
    charged, decoded = p.records, p.text_chars
    assert notes_master(p)[0] is blocks
    assert p.records == charged + 1 + len(blocks)
    assert p.text_chars == decoded


def test_null_optional_reference_never_reads_unreferenced_bytes():
    p = parser(b'not a record', pid=0)
    assert notes_master(p) == ([], set())
    assert p.records == p.text_chars == 0
    assert p.notes_master_cache is None


@pytest.mark.parametrize('raw,pid', [
    (master(), 99), (container(1016), 7), (atom(1008), 7),
    (container(1008, instance=1), 7), (container(1008), 7),
    (container(1008, drawing(b'')), 7),
    (master(extra=atom(1009, bytes(8), 1)), 7),
    (master(extra=drawing(b'')), 7),
    *[(container(1008, atom(1009, bytes(size), version, instance) + drawing(b'')), 7)
      for size, version, instance in [(7, 1, 0), (9, 1, 0), (8, 0, 0), (8, 1, 1)]],
])
def test_malformed_live_master_fails_closed(raw, pid):
    p = parser(raw, pid=pid)
    with pytest.raises(InvalidDocumentError):
        notes_master(p)
    assert p.notes_master_cache is None


def test_master_metadata_does_not_create_an_inheritance_edge():
    raw = container(1008, atom(1009, pack('<IHH', 0x80000001, 7, 0xffff), 1) + drawing(shape('Art')))
    assert notes_master(parser(raw))[0] == [(1, 'Art')]


def test_extension_warning_is_existing_diagnostic_and_deduplicated():
    p = parser(master(shape('Art'), extra=container(5000) * 2))
    assert notes_master(p)[0] == [(1, 'Art')]
    notes_master(p)
    assert p.warnings == [
        'PPT master extension records are not extracted; extension-only content may be omitted.']


def test_shape_context_restored_even_on_decode_error():
    bad = container(0xf004, atom(0xf00d, text('ok') + atom(4000, b'\x00\xd8')))
    p = parser(master(bad))
    outer, local = {10}, {9}
    p.collect_master_fields, p.local_fields = outer, local
    done = {9}
    p.inline_fields_done = done
    with pytest.raises(InvalidDocumentError):
        notes_master(p)
    assert p.collect_master_fields is outer and p.local_fields is local
    assert p.inline_fields_done is done and p.notes_master_cache is None


def test_decode_and_cached_visit_budgets():
    p = parser(master(shape('long')), replace(Limits(), max_text_chars=3))
    with pytest.raises(LimitExceededError, match='text limit'):
        notes_master(p)
    p = parser(master(shape('abc')))
    notes_master(p)
    p.limits = replace(p.limits, max_records=p.records + 1)
    with pytest.raises(LimitExceededError, match='record'):
        notes_master(p)


def presentation(flags=1, pid=4, master_raw=None):
    from test_ppt import File, persist, slide

    document_atom = bytearray(40)
    document_atom[24:28] = pack('<I', pid)
    root = container(1000, atom(1001, document_atom, 1)
                     + container(4080, persist(2, 200))
                     + container(4080, persist(3, 300), 2))
    note = container(1008, atom(1009, pack('<IHH', 200, flags, 0), 1)
                     + drawing(shape('Own note')))
    return File().edit({1: root, 2: slide(notes=300), 3: note,
                        4: master(shape('MASTER') + shape('PROMPT', placeholder=12))
                        if master_raw is None else master_raw})


@pytest.mark.parametrize('flags,expected', [(0, 'Own note'), (1, 'Own note\nMASTER'),
                                             (2, 'Own note'), (4, 'Own note')])
def test_integration_notes_own_inheritance_flag(monkeypatch, flags, expected):
    from test_ppt import run

    doc = run(monkeypatch, presentation(flags))
    assert doc.slides[0].notes == expected
    assert doc.slides[0].text == doc.slides[0].title == ''
    assert doc.warnings == []


def test_integration_disabled_or_null_edge_does_not_read_master(monkeypatch):
    from test_ppt import run

    for kwargs in ({'flags': 0}, {'pid': 0}):
        assert run(monkeypatch, presentation(master_raw=pack('<HHI', 15, 1008, 0xffffffff), **kwargs)).text == 'Own note'


def test_integration_inherited_output_budget(monkeypatch):
    from test_ppt import run

    f = presentation(master_raw=master(shape('abc')))
    # Own note + abc consumes 11 decoded characters, but the output separator
    # needs one more. The ordinary final output budget must still apply.
    with pytest.raises(LimitExceededError, match='output text'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=11))


def test_absent_optional_drawing_is_empty():
    raw = container(1008, atom(1009, bytes(8), 1))
    assert notes_master(parser(raw)) == ([], set())


def test_notes_master_cannot_alias_another_slides_notes(monkeypatch):
    from test_ppt import File, persist, run, slide

    header = bytearray(40)
    header[24:28] = pack('<I', 5)
    root = container(1000, atom(1001, header, 1)
                     + container(4080, persist(2, 200) + persist(4, 400))
                     + container(4080, persist(3, 300) + persist(5, 500), 2))
    def note(owner, value):
        return container(1008, atom(1009, pack('<IHH', owner, 1, 0), 1)
                         + drawing(shape(value)))
    f = File().edit({1: root, 2: slide(notes=300), 3: note(200, 'Notes A'),
                     4: slide(notes=500), 5: note(400, 'Notes B')})
    with pytest.raises(InvalidDocumentError, match='aliases a notes slide'):
        run(monkeypatch, f)
