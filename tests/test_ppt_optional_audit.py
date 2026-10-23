"""Optional-record audit: original wire cases, existing transport builder only.

These are parser-component streams, not a claim of full PowerPoint conformance.
See docs/PPT.md for primary contracts and boundaries.
"""
from dataclasses import replace
from struct import pack

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import File, atom, container, drawing, persist, run, text
from test_ppt_fields import fixture, hf


def extension(payload=b''):
    return container(5000, container(5002,
        atom(4026, '___PPT10'.encode('utf-16-le')) + atom(5003, payload)))


def presentation(extra=b'', notes_list=None, notes_id=0):
    # A nonzero master identity with object inheritance disabled; the master
    # list is deliberately outside this component fixture's extraction path.
    root = atom(1001, bytes(40), version=1)
    root += container(4080, persist(2, 256) + text('Body'))
    if notes_list is not None:
        root += container(4080, notes_list, 2)
    sheet = container(1006, atom(1007,
        pack('<I8sIIHH', 16, bytes(8), 0x80000000, notes_id, 0, 0), version=2) + extra)
    return File().edit({1: container(1000, root), 2: sheet})


@pytest.mark.parametrize('mask', range(8))
@pytest.mark.parametrize('empty', [False, True])
def test_comment_optional_strings_independent(monkeypatch, mask, empty):
    values = ('Author', 'Comment', 'AU') if not empty else ('', '', '')
    strings = b''.join(atom(4026, value.encode('utf-16-le'), instance=i)
                       for i, value in enumerate(values) if mask & (1 << i))
    comment = container(12000, strings + atom(12001, bytes(28)))
    result = run(monkeypatch, presentation(extension(comment)))
    expected = [value if mask & (1 << i) else '' for i, value in enumerate(values)]
    assert len(result.slides[0].comments) == 1
    actual = result.slides[0].comments[0]
    assert [actual.author, actual.text, actual.initials] == expected
    assert result.slides[0].text == 'Body'
    assert result.text == 'Body' + ('\n' + expected[1] if expected[1] else '')
    assert result.warnings == []


@pytest.mark.parametrize('extra', [b'', extension(), extension(container(11010))])
@pytest.mark.parametrize('notes_list', [None, b''])
def test_absent_notes_and_empty_extension_arrays(monkeypatch, extra, notes_list):
    result = run(monkeypatch, presentation(extra, notes_list))
    assert result.text == 'Body'
    assert result.slides[0].notes == ''
    assert result.slides[0].comments == []
    assert result.warnings == []


@pytest.mark.parametrize('local', [None, '', 'Footer'])
@pytest.mark.parametrize('date', [None, ''])
def test_enabled_optional_field_strings_absent_or_empty(monkeypatch, local, date):
    result = run(monkeypatch, fixture(
        default=hf(37, 'Do not inherit', 'Do not inherit', instance=3),
        local=hf(37, local, date)))
    assert result.text == (local or '')
    assert result.warnings == []


@pytest.mark.parametrize('slide_list', [b'', container(4080)])
def test_absent_or_zero_count_slide_list(monkeypatch, slide_list):
    f = File().edit({1: container(1000, atom(1001, bytes(40), version=1) + slide_list)})
    result = run(monkeypatch, f)
    assert result.slides == []
    assert result.text == ''
    assert result.warnings == []


@pytest.mark.parametrize('username', [b'', b'Auditor'])
@pytest.mark.parametrize('unicode_present', [False, True])
def test_optional_current_user_unicode_name(monkeypatch, username, unicode_present):
    f = presentation()
    data = pack('<IIIHHBBH', 20, 0xe391c05f, f.last_edit, len(username), 0x03f4, 3, 0, 0)
    data += username + pack('<I', 8)
    if unicode_present:
        data += username.decode('ascii').encode('utf-16-le')
    assert run(monkeypatch, f, current=atom(4086, data)).text == 'Body'


@pytest.mark.parametrize('properties', [
    atom(0xf00b, version=3),
    atom(0xf00b, pack('<HI', 0xc0, 0), version=3, instance=1),
    atom(0xf00b, pack('<HI', 0x80c0, 2) + b'\0\0', version=3, instance=1),
])
def test_empty_geometry_metadata_does_not_erase_native_body(monkeypatch, properties):
    shapes = atom(1036, container(0xf002, container(0xf004, properties)))
    assert run(monkeypatch, presentation(shapes)).text == 'Body'


@pytest.mark.parametrize('extra', [
    container(4057),  # optional container present, required flags missing
    container(4057, atom(4058, bytes(3))),
    extension(container(12000)),  # required comment settings missing
    extension(container(12000, atom(12001, bytes(27)))),
    extension(container(12000, atom(12001, bytes(28)) + atom(4026, b'x', instance=1))),
    extension(atom(12011, bytes(7))),  # recognized timing atom truncated
    extension(b'\0'),  # not a zero-element array: partial child header
    drawing(atom(3998, pack('<I', 1))),  # one outline exists, index 1 is invalid
])
def test_malformed_is_not_optional_absence(monkeypatch, extra):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, presentation(extra))


def test_nonzero_dangling_notes_still_refused(monkeypatch):
    with pytest.raises(InvalidDocumentError, match='unresolved PPT notes ID'):
        run(monkeypatch, presentation(notes_id=400))


def test_empty_comment_records_still_consume_work_budget(monkeypatch):
    extra = extension(container(12000, atom(12001, bytes(28))) * 40)
    with pytest.raises(LimitExceededError):
        run(monkeypatch, presentation(extra), replace(Limits(), max_records=30))


def test_optional_metadata_does_not_reset_text_budget(monkeypatch):
    extra = extension(container(12000, atom(12001, bytes(28))
        + atom(4026, 'ABCDE'.encode('utf-16-le'), instance=0)))
    with pytest.raises(LimitExceededError):
        run(monkeypatch, presentation(extra), replace(Limits(), max_text_chars=8))
