"""Independent wire-format cases for conservative PPT extension classification."""
from dataclasses import replace
import json
from pathlib import Path
from struct import pack

import pytest

from legacy_office_parser import parse_ppt
from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import File, atom, container, document, persist, run, slide, text


def extension(payload=b'', name='___PPT10'):
    return container(5000, container(5002, atom(4026, name.encode('utf-16-le')) + atom(5003, payload)))


def node(payload=b''):
    return container(61764, atom(61735, pack('<8I', 0, 0, 1, 3, 0, 0, 0, 24)) + payload, 1)


def role(value=9, instance=20, variant=1):
    return container(61757, atom(61762, pack('<BI', variant, value), instance=instance))


def metadata():
    condition = container(61733, atom(61736, pack('<4I', 1, 9, 0, 0))
                          + container(61756, atom(11009, pack('<I', 1))), 3)
    return (atom(12011, bytes(8)) + atom(11008, bytes(4))
            + node(role() + node(role(4) + atom(61761, pack('<5I', 1, 1, 0, 0, 3)) + condition))
            + container(11010))


def presentation(payload):
    return File().edit({1: document(persist(2, 200) + text('Visible')), 2: slide(payload)})


def test_metadata_tree_does_not_warn_or_emit_metadata(monkeypatch):
    result = run(monkeypatch, presentation(extension(metadata())))
    assert result.text == 'Visible'
    assert result.warnings == []


@pytest.mark.parametrize('payload', [b'', atom(12011, bytes(8)), atom(11008, bytes(4)),
                                     container(11010), node(), node(role())])
def test_narrow_metadata_subsets(monkeypatch, payload):
    assert run(monkeypatch, presentation(extension(payload))).warnings == []


@pytest.mark.parametrize('payload', [
    atom(0x7777, b'unknown'),
    text('extension-only text'),
    node(atom(0x7777, b'unknown nested record')),
    node(text('nested text')),
    node(container(61757, atom(61762, b'\x03' + 'string'.encode('utf-16-le'), instance=18))),
    node(role(instance=19)),  # other numeric variants are not whitelisted
    node(role(variant=3)),
    node(role(value=10)),
    node(container(61733, atom(61736, bytes(16)) + container(61756, text('target text')), 3)),
    container(11010, text('build text')),
    node(container(61746, atom(4026, 'command'.encode('utf-16-le')))),
    atom(61735, bytes(32)),  # familiar type in wrong parent
    container(61764, instance=1),  # missing required TimeNodeAtom
])
def test_unknown_or_text_bearing_content_retains_warning(monkeypatch, payload):
    result = run(monkeypatch, presentation(extension(payload)))
    assert result.text == 'Visible'
    assert len(result.warnings) == 1
    assert 'extension-only content may be omitted' in result.warnings[0]


def test_supported_comment_requires_its_settings_record(monkeypatch):
    payload = container(12000, atom(4026, 'comment text'.encode('utf-16-le'), instance=1))
    with pytest.raises(InvalidDocumentError, match='missing PPT comment settings'):
        run(monkeypatch, presentation(extension(payload)))


@pytest.mark.parametrize('name', ['___PPT9', '___PPT12', 'Custom', '___PPT10\0'])
def test_tag_name_is_not_a_blanket_allowlist(monkeypatch, name):
    assert run(monkeypatch, presentation(extension(metadata(), name))).warnings


@pytest.mark.parametrize('payload', [
    container(5000, container(5001, atom(4026, b'text'))),
    atom(5000, b'opaque'),
    container(5000, container(5002)),
    container(5000, container(5002, atom(4026, '___PPT10'.encode('utf-16-le')))),
    container(5000, container(5002, atom(4026, '___PPT10'.encode('utf-16-le'))
                              + atom(5003) + atom(5003))),
    extension(atom(12011, bytes(8), version=1)),
    extension(atom(11008, bytes(4), instance=1)),
    extension(container(61764, atom(61735, bytes(32)), instance=0)),
])
def test_unknown_envelopes_and_headers_warn(monkeypatch, payload):
    assert run(monkeypatch, presentation(payload)).warnings


@pytest.mark.parametrize('payload', [atom(12011, bytes(9)), atom(11008, bytes(3)),
                                     node(atom(61761, bytes(21))),
                                     node(container(61757, atom(61762, bytes(6), instance=20))),
                                     node(b'x'), pack('<HHI', 0, 12011, 1000)])
def test_malformed_recognized_records_fail_closed(monkeypatch, payload):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, presentation(extension(payload)))


def test_unknown_sibling_cannot_be_hidden_by_known_tag(monkeypatch):
    known = container(5002, atom(4026, '___PPT10'.encode('utf-16-le')) + atom(5003, metadata()))
    for body in (known + container(5001, text('opaque')), container(5001, text('opaque')) + known,
                 known + known):
        assert run(monkeypatch, presentation(container(5000, body))).warnings


@pytest.mark.parametrize('field,value', [('max_records', 18), ('max_depth', 6)])
def test_extension_traversal_uses_shared_limits(monkeypatch, field, value):
    with pytest.raises(LimitExceededError):
        run(monkeypatch, presentation(extension(metadata())), replace(Limits(), **{field: value}))


def test_deep_timing_tree_is_bounded_without_python_recursion(monkeypatch):
    payload = node()
    for _ in range(100):
        payload = node(payload)
    with pytest.raises(LimitExceededError, match='depth'):
        run(monkeypatch, presentation(extension(payload)), replace(Limits(), max_depth=20))


def test_120_slide_metadata_and_content_are_preserved(monkeypatch):
    objects = {1: document(b''.join(persist(i + 2, i + 200) + text(f'Slide {i}') for i in range(120)))}
    objects.update({i + 2: slide(extension(metadata())) for i in range(120)})
    result = run(monkeypatch, File().edit(objects))
    assert [s.text for s in result.slides] == [f'Slide {i}' for i in range(120)]
    assert result.warnings == []


def test_original_libreoffice_fixture_fidelity_and_no_extension_warning():
    fixtures = Path(__file__).parent / 'fixtures'
    actual = parse_ppt(fixtures / 'slides_notes.ppt').to_dict()
    expected = json.loads((fixtures / 'slides_notes.expected.json').read_text())
    assert actual.pop('warnings') == []
    expected.pop('warnings')
    assert actual == expected


def test_notes_context_is_not_classified_as_slide_metadata(monkeypatch):
    notes = container(1008, atom(1009, pack('<IHH', 200, 0, 0), version=1)
                      + extension(metadata()))
    f = File().edit({1: document(persist(2, 200), persist(3, 300)),
                     2: slide(notes=300), 3: notes})
    assert run(monkeypatch, f).warnings


def test_deleted_extension_objects_are_not_traversed(monkeypatch):
    f = presentation(extension(metadata()))
    f.edit({2: slide()})
    f.put(slide(extension(node(b'x'))))
    result = run(monkeypatch, f)
    assert result.text == 'Visible'
    assert result.warnings == []
