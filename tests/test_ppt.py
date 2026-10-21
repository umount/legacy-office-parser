"""Synthetic PPT streams, independent of external office applications or files."""
from contextlib import contextmanager
from dataclasses import replace
from struct import pack, pack_into

import pytest

from legacy_office_parser import ppt
from legacy_office_parser.errors import (InvalidDocumentError, LimitExceededError,
                                         EncryptedDocumentError, UnsupportedFormatError)
from legacy_office_parser.limits import Limits


def atom(typ, payload=b'', version=0, instance=0):
    return pack('<HHI', version | (instance << 4), typ, len(payload)) + payload


def container(typ, payload=b'', instance=0):
    return atom(typ, payload, 15, instance)


def text(value, kind=1, unicode=True):
    return atom(3999, pack('<I', kind)) + atom(4000 if unicode else 4008, value.encode('utf-16-le' if unicode else 'latin-1'))


def persist(pid, sid):
    return atom(1011, pack('<IIIII', pid, 0, 0, sid, 0))


def drawing(payload, depth=0):
    value = atom(0xf00d, payload)
    value = container(0xf004, value)
    for _ in range(depth):
        value = container(0xf003, value)
    return atom(1036, container(0xf002, value))


def slide(payload=b'', notes=0):
    return container(1006, atom(1007, pack('<I8sIIHH', 0, b'\x00' * 8, 0, notes, 0, 0), 2) + payload)


def note(sid, value):
    return container(1008, atom(1009, pack('<IHH', sid, 0, 0), 1) + drawing(text(value, 2)))


class File:
    def __init__(self):
        self.data = bytearray()
        self.last_edit = 0

    def put(self, record):
        pos = len(self.data)
        self.data.extend(record)
        return pos

    def edit(self, objects):
        offsets = {pid: self.put(value) for pid, value in objects.items()}
        directory = self.put(atom(6002, b''.join(pack('<II', (1 << 20) | pid, offset) for pid, offset in offsets.items())))
        self.last_edit = self.put(atom(4085, pack('<IIIIIIHH', 0, 0x03000000, self.last_edit, directory, 1, max(objects) + 1, 0, 0)))
        return self

    def current(self):
        return atom(4086, pack('<IIIHHBBHI', 20, 0xe391c05f, self.last_edit, 0, 0x03f4, 3, 0, 0, 8))


def document(slides, notes=b''):
    return container(1000, container(4080, slides) + container(4080, notes, 2))


def run(monkeypatch, file, limits=Limits(), current=None):
    streams = {'Current User': current if current is not None else file.current(), 'PowerPoint Document': bytes(file.data)}
    class Ole:
        def exists(self, name):
            return name in streams
    @contextmanager
    def open_ole(data, limits):
        yield Ole()
    def read_stream(ole, name, limits):
        if len(streams[name]) > limits.max_stream_bytes:
            raise LimitExceededError('stream')
        return streams[name]
    monkeypatch.setattr(ppt, 'open_ole', open_ole)
    monkeypatch.setattr(ppt, 'read_stream', read_stream)
    return ppt.parse_ppt_bytes(b'fixture', limits)


def test_blank_slides_outline_and_shape_text_and_order(monkeypatch):
    f = File().edit({1: document(persist(3, 301) + persist(2, 302) + text('Title', 0) + text('Body') + persist(4, 303)),
                     2: slide(drawing(atom(3998, pack('<I', 1)) + text('Shape'))),
                     3: slide(), 4: slide()})
    result = run(monkeypatch, f)
    assert [s.number for s in result.slides] == [1, 2, 3]
    assert result.slides[0].text == result.slides[2].text == ''
    assert result.slides[1].title == 'Title'
    assert result.slides[1].text == 'Body\nShape'


def test_notes_use_ids_not_position_and_require_backlink(monkeypatch):
    f = File().edit({1: document(persist(2, 900) + persist(3, 800), persist(5, 70) + persist(4, 60)),
                     2: slide(notes=60), 3: slide(notes=70),
                     4: note(900, 'first'), 5: note(800, 'second')})
    assert [s.notes for s in run(monkeypatch, f).slides] == ['first', 'second']
    f.edit({5: note(900, 'wrong')})
    with pytest.raises(InvalidDocumentError, match='backlink'):
        run(monkeypatch, f)


def test_latest_persist_wins_deleted_objects_never_scanned(monkeypatch):
    f = File().edit({1: document(persist(2, 200) + text('old') + persist(3, 300) + text('deleted')),
                     2: slide(drawing(text('stale shape'))), 3: slide()})
    f.edit({1: document(persist(4, 400) + text('new') + persist(2, 200)),
            2: slide(drawing(text('replacement'))), 4: slide()})
    f.put(slide(drawing(text('unreferenced appended data'))))
    result = run(monkeypatch, f)
    assert [s.text for s in result.slides] == ['new', 'replacement']


def test_unchanged_objects_inherited_from_older_directory(monkeypatch):
    f = File().edit({1: document(persist(2, 200)), 2: slide(drawing(text('kept')))})
    f.edit({1: document(persist(2, 200))})
    assert run(monkeypatch, f).slides[0].text == 'kept'


def test_repeated_shape_text_is_not_value_deduplicated(monkeypatch):
    f = File().edit({1: document(persist(2, 200) + text('same')),
                     2: slide(drawing(text('same')) + drawing(text('same')))})
    assert run(monkeypatch, f).slides[0].text == 'same\nsame\nsame'


def test_unicode_latin1_line_breaks_hidden_and_nested_shapes(monkeypatch):
    flags = bytearray(16)
    flags[10] = 4
    f = File().edit({1: document(persist(2, 200)),
                     2: slide(atom(1017, flags) + drawing(text('Привет\r世界\v😀', 6) + text('\x80é', unicode=False), 2))})
    s = run(monkeypatch, f).slides[0]
    assert s.title == 'Привет\n世界\n😀'
    assert s.text == '\x80é'
    assert s.hidden


@pytest.mark.parametrize('field,value', [('max_records', 3), ('max_depth', 3), ('max_text_chars', 2), ('max_slides', 1)])
def test_limits(monkeypatch, field, value):
    f = File().edit({1: document(persist(2, 200) + persist(3, 300)),
                     2: slide(drawing(text('long text'), 2)), 3: slide()})
    with pytest.raises(LimitExceededError):
        run(monkeypatch, f, replace(Limits(), **{field: value}))


def test_edit_cycle(monkeypatch):
    f = File().edit({1: document(b'')})
    pack_into('<I', f.data, f.last_edit + 16, f.last_edit)
    with pytest.raises(InvalidDocumentError, match='cycle'):
        run(monkeypatch, f)


@pytest.mark.parametrize('payload', [atom(3998, pack('<I', 2)), text('x')[:-1], atom(3999, b'\x01')])
def test_bad_text_records(monkeypatch, payload):
    f = File().edit({1: document(persist(2, 200)), 2: slide(drawing(payload))})
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, f)


@pytest.mark.parametrize('payload', [b'x', b'\x00\xd8'])
def test_invalid_utf16(monkeypatch, payload):
    f = File().edit({1: document(persist(2, 200) + atom(3999, pack('<I', 1)) + atom(4000, payload)), 2: slide()})
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, f)


def test_unresolved_slide_and_notes(monkeypatch):
    for objects in ({1: document(persist(2, 200))}, {1: document(persist(2, 200)), 2: slide(notes=123)}):
        with pytest.raises(InvalidDocumentError, match='unresolved'):
            run(monkeypatch, File().edit(objects))


def test_current_user_encryption_version_and_offset(monkeypatch):
    f = File().edit({1: document(b'')})
    for offset, value, error in [(12, 0xf3d1c4df, EncryptedDocumentError), (12, 0, UnsupportedFormatError), (16, 0xffffffff, InvalidDocumentError)]:
        current = bytearray(f.current())
        pack_into('<I', current, offset, value)
        with pytest.raises(error):
            run(monkeypatch, f, current=bytes(current))


def test_no_slides_does_not_fallback_to_any_text(monkeypatch):
    f = File().edit({1: document(b''), 2: slide(drawing(text('dead')))})
    assert run(monkeypatch, f).slides == []


def test_unlinked_notes_never_extracted(monkeypatch):
    f = File().edit({1: document(persist(2, 200), persist(3, 300)), 2: slide(), 3: note(200, 'not linked')})
    assert run(monkeypatch, f).slides[0].notes == ''


def test_duplicate_ids_and_parent_bounds(monkeypatch):
    f = File().edit({1: document(persist(2, 200) + persist(2, 200)), 2: slide()})
    with pytest.raises(InvalidDocumentError, match='duplicate'):
        run(monkeypatch, f)
    f = File().edit({1: document(persist(2, 200)), 2: container(1006, pack('<HHI', 2, 1007, 999999))})
    with pytest.raises(InvalidDocumentError, match='bounds'):
        run(monkeypatch, f)


def test_bad_directory_runs_and_offsets(monkeypatch):
    for packed in (0, 1, (4095 << 20) | 1):
        f = File().edit({1: document(b'')})
        directory = int.from_bytes(f.data[f.last_edit + 20:f.last_edit + 24], 'little')
        pack_into('<I', f.data, directory + 8, packed)
        with pytest.raises(InvalidDocumentError, match='directory run'):
            run(monkeypatch, f)
    f = File().edit({1: document(b'')})
    directory = int.from_bytes(f.data[f.last_edit + 20:f.last_edit + 24], 'little')
    pack_into('<I', f.data, directory + 12, 0xffffffff)
    with pytest.raises(InvalidDocumentError, match='offset'):
        run(monkeypatch, f)


def test_encryption_reference_rejected(monkeypatch):
    f = File().edit({1: document(b'')})
    pack_into('<I', f.data, f.last_edit + 4, 32)
    f.data.extend(pack('<I', 9))
    with pytest.raises(EncryptedDocumentError):
        run(monkeypatch, f)


def test_output_separators_are_bounded(monkeypatch):
    f = File().edit({1: document(persist(2, 200) + text('x', 0) + text('y')), 2: slide()})
    with pytest.raises(LimitExceededError, match='output'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=2))


def test_unsupported_extensions_warn_without_scanning_strings(monkeypatch):
    f = File().edit({1: document(persist(2, 200)),
                     2: slide(container(5000, text('extension')) + atom(4026, 'metadata'.encode('utf-16-le')))})
    result = run(monkeypatch, f)
    assert result.text == ''
    assert len(result.warnings) == 1


def test_malformed_deleted_slide_is_not_parsed(monkeypatch):
    f = File().edit({1: document(b''), 2: pack('<HHI', 15, 1006, 0xffffffff)})
    assert run(monkeypatch, f).slides == []


def test_wrong_persist_type(monkeypatch):
    f = File().edit({1: document(persist(2, 200)), 2: note(200, 'wrong type')})
    with pytest.raises(InvalidDocumentError, match='object type'):
        run(monkeypatch, f)


def test_current_user_truncation_and_version(monkeypatch):
    f = File().edit({1: document(b'')})
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, f, current=f.current()[:-1])
    current = bytearray(f.current())
    current[24] = 2
    with pytest.raises(UnsupportedFormatError, match='version'):
        run(monkeypatch, f, current=bytes(current))
