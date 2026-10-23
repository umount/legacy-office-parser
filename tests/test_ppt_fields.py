"""Authored static PPT field records; no time-dependent expected results."""
from dataclasses import replace
from pathlib import Path
from struct import pack
import hashlib

import pytest

from legacy_office_parser import ppt
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import File, atom, container, persist, run, text
from test_ppt_master_text import MASTER, shape, drawing


def hf(flags=0x25, footer='Footer', date='Fixed date', instance=0, extra=b''):
    strings = b''
    for number, value in ((0, date), (2, footer)):
        if value is not None:
            strings += atom(4026, value.encode('utf-16-le'), instance=number)
    return container(4057, atom(4058, pack('<HH', 0, flags)) + strings + extra, instance)


def doc_atom(omit=False):
    raw = bytearray(40)
    raw[37] = int(omit)
    return atom(1001, raw, version=1)


def slide(payload=b'', master=MASTER, objects=True, layout=16, typ=1006):
    return container(typ, atom(1007, pack('<I8sIIHH', layout, bytes(8), master, 0,
                                         int(objects), 0), version=2) + payload)


def fixture(local=None, default=None, master_payload=None, objects=True,
            omit=False, layout=16, slide_payload=b'', count=1):
    if master_payload is None:
        master_payload = drawing(shape('DATE PROMPT', placeholder=7)
                                 + shape('NUMBER PROMPT', placeholder=8)
                                 + shape('FOOTER PROMPT', placeholder=9))
    root = container(1000, doc_atom(omit) + (default or b'')
                     + container(4080, persist(3, MASTER), 1)
                     + container(4080, b''.join(persist(10+i, 200+i) for i in range(count))))
    items = {1: root, 3: slide(master_payload, master=0, objects=False, typ=1016)}
    items.update({10+i: slide(slide_payload + (local or b''), objects=objects, layout=layout)
                  for i in range(count)})
    return File().edit(items)


@pytest.mark.parametrize('flags,expected,warning', [
    (0, '', None), (4, '', None), (32, 'Footer', None),
    (5, 'Fixed date', None), (37, 'Fixed date\nFooter', None),
    (3, '', 'active date field'), (7, '', 'active date field'),
    (1, '', 'active date field'), (8, '', 'active slide-number field'),
    (16, '', None), (0xfc20, 'Footer', None),
])
def test_active_flags_select_only_stored_static_text(monkeypatch, flags, expected, warning):
    result = run(monkeypatch, fixture(local=hf(flags)))
    assert result.text == expected
    assert not result.slides[0].title
    if warning:
        assert any(warning in w for w in result.warnings)
    else:
        assert result.warnings == []


def test_slide_container_overrides_defaults_including_disabled_fields(monkeypatch):
    default = hf(37, footer='Default footer', date='Default date', instance=3)
    assert run(monkeypatch, fixture(default=default)).text == 'Default date\nDefault footer'
    assert run(monkeypatch, fixture(default=default, local=hf(0))).text == ''
    assert run(monkeypatch, fixture(default=default, local=hf(32, 'Local footer'))).text == 'Local footer'
    # Omitted optional local strings are empty, never inherited from default.
    result = run(monkeypatch, fixture(default=default, local=hf(37, None, None)))
    assert result.text == ''
    assert result.warnings == []


def test_only_document_slide_default_is_used(monkeypatch):
    notes = hf(37, 'Notes footer', 'Notes date', instance=4)
    assert run(monkeypatch, fixture(default=notes)).text == ''


def test_unicode_line_breaks_and_repeated_identical_values(monkeypatch):
    result = run(monkeypatch, fixture(local=hf(37, 'Привет\r世界 😀', 'Привет\r世界 😀'), count=2))
    assert [s.text for s in result.slides] == ['Привет\n世界 😀\nПривет\n世界 😀'] * 2


@pytest.mark.parametrize('layout,omit,expected', [(0, True, ''), (0, False, 'Footer'),
                                                (16, True, 'Footer')])
def test_title_placeholder_suppression(monkeypatch, layout, omit, expected):
    result = run(monkeypatch, fixture(local=hf(32), layout=layout, omit=omit))
    assert result.text == expected
    assert result.warnings == []


@pytest.mark.parametrize('master_payload,objects', [(drawing(shape('ordinary')), True),
                                                    (None, False),
                                                    (drawing(shape('hidden', placeholder=9, flags=8)), True),
                                                    (drawing(shape('background', placeholder=9, flags=1024)), True)])
def test_uncertain_or_unavailable_placement_warns_without_text(monkeypatch, master_payload, objects):
    result = run(monkeypatch, fixture(local=hf(32), master_payload=master_payload, objects=objects))
    assert 'Footer' not in result.text
    assert any('unresolved placement or visibility' in w for w in result.warnings)


def test_master_only_settings_do_not_become_slide_defaults(monkeypatch):
    master_payload = drawing(shape('prompt', placeholder=9)) + hf(32, 'Master-only value')
    result = run(monkeypatch, fixture(master_payload=master_payload))
    assert result.text == ''
    assert any('active master header/footer settings' in w for w in result.warnings)


def test_active_field_warnings_are_deduplicated(monkeypatch):
    result = run(monkeypatch, fixture(default=hf(11, instance=3), count=10))
    assert result.text.strip() == ''
    assert len(result.warnings) == 2


def test_native_slide_footer_text_is_not_merged_twice(monkeypatch):
    local = drawing(shape('Stored locally', placeholder=9))
    result = run(monkeypatch, fixture(local=hf(32, 'Stored locally'), slide_payload=local))
    assert result.text == 'Stored locally'
    assert any('not merged' in w for w in result.warnings)


def test_roundtrip_field_shapes_are_not_merged_with_legacy_strings(monkeypatch):
    local = drawing(shape('Modern stored value', extra=container(0xf011, atom(1056, b'\x09'))))
    result = run(monkeypatch, fixture(local=hf(32, 'Legacy alternate'), slide_payload=local))
    assert result.text == 'Modern stored value'
    assert any('not merged' in w for w in result.warnings)


@pytest.mark.parametrize('marker', [4056, 4087, 4088, 4089, 4090])
def test_inline_field_markers_warn_without_evaluation(monkeypatch, marker):
    payload = text('stored*text') + atom(marker, bytes(8 if marker == 4087 else 4))
    local = drawing(container(0xf004, atom(0xf00d, payload)))
    result = run(monkeypatch, fixture(slide_payload=local))
    assert result.text == 'stored*text'
    assert any('field markers are not evaluated' in w for w in result.warnings)


def test_latest_slide_settings_win_and_dead_settings_are_not_scanned(monkeypatch):
    f = fixture(local=hf(32, 'old'))
    f.edit({10: slide(hf(32, 'new')), 99: slide(hf(32, 'unreferenced'))})
    f.put(slide(hf(32, 'appended')))
    assert run(monkeypatch, f).text == 'new'


@pytest.mark.parametrize('bad', [
    container(4057), atom(4057, atom(4058, bytes(4))),
    container(4057, atom(4058, bytes(3))),
    container(4057, atom(4058, bytes(4)) * 2),
    hf(extra=atom(4026, b'x', instance=2)),
    hf(extra=atom(4026, b'x\0', instance=2)),
    hf(date='x' * 256),
    container(4057, atom(4058, pack('<HH', 0, 32)) + atom(4026, b'\x00\xd8', instance=2)),
])
def test_malformed_active_settings_fail_closed(monkeypatch, bad):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, fixture(local=bad))


def test_duplicate_containers_fail_closed(monkeypatch):
    for settings in ({'local': hf() + hf()}, {'default': hf(instance=3) + hf(instance=3)}):
        with pytest.raises(InvalidDocumentError, match='duplicate'):
            run(monkeypatch, fixture(**settings))


def test_hidden_strings_are_not_decoded(monkeypatch):
    disabled = container(4057, atom(4058, bytes(4)) + atom(4026, b'\x00\xd8', instance=2))
    assert run(monkeypatch, fixture(local=disabled)).text == ''


def test_reused_default_strings_and_output_separators_are_bounded(monkeypatch):
    f = fixture(default=hf(32, 'abc', None, instance=3), count=2)
    with pytest.raises(LimitExceededError, match='text limit'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=5))
    with pytest.raises(LimitExceededError, match='output text limit'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=7))
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=8)).text == 'abc\n\nabc'


def test_original_libreoffice_static_fields(monkeypatch):
    raw = (Path(__file__).parent / 'fixtures/ppt_fields/static_fields.ppt').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'ebd05d26ee50d3d5160820d2b5d8d634ea41bfe1a91b0500b164808a98f53192'
    result = ppt.parse_ppt_bytes(raw, Limits())
    # Literal authored text and independent UNO visibility/readback, not output
    # generated by this parser. Hidden slide-2 strings remain stored in the file.
    assert [s.text for s in result.slides] == [
        'Body 1\nFixed date / 2040-06-17\nStored footer / Привет',
        'Body 2',
        'Body 3\nAnother stored date\nDifferent footer',
    ]
    assert all(s.title == s.notes == '' for s in result.slides)
    assert result.warnings == ['PPT active slide-number field is not evaluated; no generated value is extracted.']
    monkeypatch.setattr(ppt._Parser, 'static_slide_fields', lambda self, *args: [])
    assert [s.text for s in ppt.parse_ppt_bytes(raw, Limits()).slides] == ['Body 1', 'Body 2', 'Body 3']


def test_footer_matching_ordinary_body_is_not_value_deduplicated(monkeypatch):
    result = run(monkeypatch, fixture(local=hf(32, 'same'), slide_payload=drawing(shape('same'))))
    assert result.text == 'same\nsame'


def test_fixed_date_format_id_is_ignored(monkeypatch):
    fixed = container(4057, atom(4058, pack('<HH', 0xffff, 5))
                      + atom(4026, 'Literal date'.encode('utf-16-le')))
    assert run(monkeypatch, fixture(local=fixed)).text == 'Literal date'


@pytest.mark.parametrize('marker', [4056, 4087, 4088, 4089, 4090])
@pytest.mark.parametrize('fault', ['empty', 'short', 'long', 'version', 'instance', 'position', 'orphan'])
def test_invalid_mc_metadata_cannot_suppress_static_fields(monkeypatch, marker, fault):
    size = 8 if marker == 4087 else 4
    payload = bytes(size)
    if fault in ('empty', 'short', 'long'):
        payload = bytes({'empty': 0, 'short': size - 1, 'long': size + 1}[fault])
    if fault == 'position':
        payload = pack('<I', 1) + payload[4:]
    record = atom(marker, payload, version=int(fault == 'version'), instance=int(fault == 'instance'))
    raw = (b'' if fault == 'orphan' else text('*')) + record
    local = drawing(container(0xf004, atom(0xf00d, raw)))
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, fixture(local=hf(37), slide_payload=local))


@pytest.mark.parametrize('payload,version,instance', [
    (b'', 0, 0), (b'\x09\x00', 0, 0), (b'\x00', 0, 0),
    (b'\x06', 0, 0), (b'\x0b', 0, 0), (b'\xff', 0, 0),
    (b'\x09', 1, 0), (b'\x09', 0, 1),
])
def test_invalid_roundtrip_metadata_cannot_suppress_footer(monkeypatch, payload, version, instance):
    local = drawing(shape('Local', extra=container(0xf011, atom(1056, payload, version, instance))))
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, fixture(local=hf(32), slide_payload=local))


@pytest.mark.parametrize('identifier', [7, 8, 9, 10])
def test_valid_roundtrip_field_ids_remain_conservative(monkeypatch, identifier):
    local = drawing(shape('Local', extra=container(0xf011, atom(1056, bytes([identifier])))))
    result = run(monkeypatch, fixture(local=hf(32), slide_payload=local))
    assert result.text == 'Local'
    assert any('not merged' in warning for warning in result.warnings)


def test_datetime_format_index_is_validated_without_evaluation(monkeypatch):
    local = drawing(container(0xf004, atom(0xf00d, text('*') + atom(4087, bytes(4) + b'\x0d\x00\x00\x00'))))
    with pytest.raises(InvalidDocumentError, match='format index'):
        run(monkeypatch, fixture(local=hf(), slide_payload=local))


def test_field_positions_use_original_utf16_units(monkeypatch):
    # Supplementary character and trailing whitespace survive position checks
    # even though normalization strips whitespace from the returned text.
    raw = text('😀 * ') + atom(4090, pack('<I', 4))
    local = drawing(container(0xf004, atom(0xf00d, raw)))
    result = run(monkeypatch, fixture(local=hf(32), slide_payload=local))
    assert result.text == '😀 *'
    assert any('not merged' in warning for warning in result.warnings)


def test_notes_static_fields_and_inline_values_use_notes_settings(monkeypatch):
    from test_ppt import slide as plain_slide
    from test_ppt_inline_fields import inline, marker

    settings = hf(53, 'Notes footer', 'Fixed date', instance=4,
                  extra=atom(4026, 'Notes header'.encode('utf-16le'), instance=1))
    header = bytearray(40)
    header[24:28] = pack('<I', 4)
    root = container(1000, atom(1001, header, version=1) + settings
                     + container(4080, persist(2, 200))
                     + container(4080, persist(3, 300), 2))
    master = container(1008, atom(1009, bytes(8), version=1) + drawing(
        shape('date prompt', placeholder=7) + shape('footer prompt', placeholder=9)
        + shape('header prompt', placeholder=10)))
    for payload, expected in [
        (drawing(shape('Speaker notes')), 'Speaker notes\nFixed date\nNotes footer\nNotes header'),
        (inline(text('* / * / *') + marker(0, 4089) + marker(4, 4088) + marker(8)),
         'Notes header / Fixed date / Notes footer'),
    ]:
        notes = container(1008, atom(1009, pack('<IHH', 200, 1, 0), version=1) + payload)
        result = run(monkeypatch, File().edit({1: root, 2: plain_slide(notes=300), 3: notes, 4: master}))
        assert result.slides[0].notes == expected
        assert result.slides[0].text == ''
        assert result.warnings == []
