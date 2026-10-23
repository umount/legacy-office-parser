"""Original wire fixtures; expected strings are authored independently of parsing."""
from dataclasses import replace
from struct import pack

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import File, atom, container, persist, run, text


MASTER = 0x80000001
TITLE_MASTER = 0x80000002


def shape(value, placeholder=None, flags=0, kind=1, extra=b''):
    client = b'' if placeholder is None else container(
        0xf011, atom(3011, pack('<IBBH', 0xffffffff, placeholder, 0, 0)))
    return container(0xf004, atom(0xf00a, pack('<II', 1025, flags), 2)
                     + atom(0xf00d, text(value, kind)) + extra + client)


def drawing(shapes):
    return atom(1036, container(0xf002, shapes))


def sheet(shapes=b'', master=MASTER, flags=1, typ=1006):
    return container(typ, atom(1007, pack('<I8sIIHH', 0, bytes(8), master, 0, flags, 0), 2)
                     + drawing(shapes))


def root(slides=None, masters=None):
    return container(1000, container(4080, persist(2, 200) if slides is None else slides)
                     + container(4080, persist(3, MASTER) if masters is None else masters, 1))


def fixture(shapes, flags=1):
    return File().edit({1: root(), 2: sheet(shape('Slide body'), flags=flags),
                        3: sheet(shapes, master=0, flags=0, typ=1016)})


@pytest.mark.parametrize('flags,expected', [
    (0, 'Slide body'), (1, 'Slide body\nMaster label'),
    (2, 'Slide body'), (4, 'Slide body'), (5, 'Slide body\nMaster label'),
    (7, 'Slide body\nMaster label'),
])
def test_objects_flag_independent_of_background_and_scheme(monkeypatch, flags, expected):
    assert run(monkeypatch, fixture(shape('Master label'), flags)).text == expected


def test_placeholders_are_not_inherited_or_used_as_titles(monkeypatch):
    master = b''.join(shape('template or field', placeholder=i) for i in range(1, 27))
    master += shape('Ordinary master heading', kind=0) + shape('Привет 世界 😀\rline')
    result = run(monkeypatch, fixture(master))
    assert result.slides[0].title == ''
    assert result.text == 'Slide body\nOrdinary master heading\nПривет 世界 😀\nline'


def test_identical_text_on_distinct_shapes_and_slides_survives(monkeypatch):
    f = File().edit({1: root(persist(2, 200) + persist(4, 400)),
                     2: sheet(shape('same')), 4: sheet(),
                     3: sheet(shape('same') + shape('same'), master=0, flags=0, typ=1016)})
    result = run(monkeypatch, f)
    assert [s.text for s in result.slides] == ['same\nsame\nsame', 'same\nsame']


def test_grouped_master_text_and_deleted_groups(monkeypatch):
    group = container(0xf003, shape('', flags=1) + shape('Grouped'))
    deleted = container(0xf003, shape('', flags=9) + shape('Deleted group child'))
    f = fixture(group + deleted + shape('Deleted', flags=8) + shape('Background', flags=1024))
    assert run(monkeypatch, f).text == 'Slide body\nGrouped'


def test_master_wordart_same_shape_fallback(monkeypatch):
    raw = 'WordArt\x00'.encode('utf-16-le')
    props = atom(0xf00b, pack('<HI', 0x80c0, len(raw)) + raw, 3, 1)
    f = fixture(shape('WordArt', extra=props) + shape('', extra=props)
                + shape('Template', placeholder=1, extra=props))
    assert run(monkeypatch, f).text == 'Slide body\nWordArt\nWordArt'


@pytest.mark.parametrize('flags,expected', [(0, 'Title artwork'), (1, 'Title artwork\nMain artwork')])
def test_title_master_follows_its_own_objects_flag(monkeypatch, flags, expected):
    f = File().edit({1: root(masters=persist(3, MASTER) + persist(4, TITLE_MASTER)),
                     2: sheet(master=TITLE_MASTER),
                     3: sheet(shape('Main artwork'), master=0, flags=0, typ=1016),
                     4: sheet(shape('Title artwork') + shape('Prompt', placeholder=3), flags=flags)})
    assert run(monkeypatch, f).text == expected


def test_replaced_and_unused_masters_never_leak(monkeypatch):
    f = fixture(shape('Old master'))
    f.edit({3: sheet(shape('Current master'), master=0, flags=0, typ=1016),
            5: sheet(shape('Unlisted master'), master=0, flags=0, typ=1016)})
    f.put(sheet(shape('Appended master'), master=0, flags=0, typ=1016))
    assert run(monkeypatch, f).text == 'Slide body\nCurrent master'
    f.edit({1: root(masters=persist(3, MASTER) + persist(6, TITLE_MASTER)),
            6: pack('<HHI', 15, 1016, 0xffffffff)})
    assert run(monkeypatch, f).text == 'Slide body\nCurrent master'


def test_disabled_master_is_not_resolved(monkeypatch):
    f = File().edit({1: root(masters=b''), 2: sheet(shape('Only local'), flags=4)})
    assert run(monkeypatch, f).text == 'Only local'


@pytest.mark.parametrize('master', [0, 123, MASTER])
def test_unresolved_enabled_master_fails_closed(monkeypatch, master):
    f = File().edit({1: root(masters=b''), 2: sheet(master=master)})
    with pytest.raises(InvalidDocumentError, match='master reference'):
        run(monkeypatch, f)


def test_master_cycle_and_chain_depth(monkeypatch):
    f = File().edit({1: root(masters=persist(3, MASTER) + persist(4, TITLE_MASTER)),
                     2: sheet(), 3: sheet(master=TITLE_MASTER), 4: sheet(master=MASTER)})
    with pytest.raises(InvalidDocumentError, match='cyclic'):
        run(monkeypatch, f)
    # Long acyclic chain, bounded separately from record nesting.
    entries = b''.join(persist(3+i, MASTER+i) for i in range(10))
    objects = {1: root(masters=entries), 2: sheet()}
    objects.update({3+i: sheet(master=MASTER+i+1) for i in range(9)})
    objects[12] = sheet(master=0, flags=0, typ=1016)
    with pytest.raises(LimitExceededError, match='inheritance depth'):
        run(monkeypatch, File().edit(objects), replace(Limits(), max_depth=8))


@pytest.mark.parametrize('bad', [
    container(1008), container(1016),
    sheet(master=MASTER, typ=1016),
    container(1016, atom(1007, bytes(23))),
    container(1016, atom(1007, bytes(24)) + atom(1007, bytes(24))),
    sheet(container(0xf004, container(0xf011, atom(3011, bytes(7)))), master=0, typ=1016),
    sheet(container(0xf004, atom(0xf00a, bytes(7), 2)), master=0, typ=1016),
])
def test_malformed_live_master_fails_closed(monkeypatch, bad):
    f = File().edit({1: root(), 2: sheet(), 3: bad})
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, f)


def test_master_decode_and_repeated_output_budgets(monkeypatch):
    with pytest.raises(LimitExceededError, match='text limit'):
        run(monkeypatch, fixture(shape('Long master text')), replace(Limits(), max_text_chars=12))
    f = File().edit({1: root(persist(2, 200) + persist(4, 400)),
                     2: sheet(), 4: sheet(),
                     3: sheet(shape('abc'), master=0, flags=0, typ=1016)})
    with pytest.raises(LimitExceededError, match='output text'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=7))
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=8)).text == 'abc\n\nabc'


def test_master_record_budget(monkeypatch):
    with pytest.raises(LimitExceededError, match='record'):
        run(monkeypatch, fixture(shape('label') * 30), replace(Limits(), max_records=80))


@pytest.mark.parametrize('record_type', [0xf00b, 0xf122])
@pytest.mark.parametrize('pid,value,visible', [
    (0x3bf, 0x20002, False), (0x3bf, 2, True), (0x3bf, 0x20000, True),
    (0x33f, 0x10001, False), (0x33f, 1, True), (0x33f, 0x10000, True),
])
def test_explicit_visibility_properties(monkeypatch, record_type, pid, value, visible):
    props = atom(record_type, pack('<HI', pid, value), 3, 1)
    result = run(monkeypatch, fixture(shape('Label', extra=props)))
    assert result.text == ('Slide body\nLabel' if visible else 'Slide body')


def test_hidden_group_does_not_leak_children(monkeypatch):
    props = atom(0xf00b, pack('<HI', 0x3bf, 0x20002), 3, 1)
    group = container(0xf003, shape('', flags=1, extra=props) + shape('Hidden child'))
    assert run(monkeypatch, fixture(group)).text == 'Slide body'


def test_original_libreoffice_master_objects(monkeypatch):
    from pathlib import Path
    import hashlib
    from legacy_office_parser import ppt

    raw = (Path(__file__).parent / 'fixtures/ppt_master/master_objects.ppt').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '7d932d6c1ab3ab1bde31acdfa7ff06832641aa910beceff8c91e5e34f4922077'
    result = ppt.parse_ppt_bytes(raw, Limits())
    # Literal authored expectation; independently reopened via LibreOffice UNO.
    # Its master identifies the notice as IsPresentationObject=False; title,
    # outline, date, footer and number shapes are all presentation placeholders.
    assert [s.text for s in result.slides] == [
        'Slide 1\nMASTER NOTICE / Привет 世界',
        'Slide 2',
        'Slide 3\nMASTER NOTICE / Привет 世界',
    ]
    assert all(s.title == s.notes == '' for s in result.slides)
    assert result.warnings == []
    # This fixture proves the omission: ordinary slide text cannot supply it.
    monkeypatch.setattr(ppt._Parser, 'master_text', lambda self, master_id: [])
    assert ppt.parse_ppt_bytes(raw, Limits()).text == 'Slide 1\n\nSlide 2\n\nSlide 3'


def test_current_master_list_selection_and_unreferenced_outline(monkeypatch):
    f = fixture(shape('Former master'))
    f.edit({1: root(masters=persist(4, TITLE_MASTER) + text('Unused list text')),
            2: sheet(shape('Local'), master=TITLE_MASTER),
            4: sheet(shape('Selected master'), master=0, flags=0, typ=1016)})
    assert run(monkeypatch, f).text == 'Local\nSelected master'


def test_placeholder_prompts_are_not_decoded(monkeypatch):
    # Bad UTF-16 in excluded template text cannot become a fallback or consume
    # content budget. Record bounds and placeholder metadata are still checked.
    prompt = container(0xf004, atom(0xf00d, atom(3999, pack('<I', 0))
                                   + atom(4000, b'\x00\xd8'))
                       + container(0xf011, atom(3011, pack('<IBBH', 0, 1, 0, 0))))
    assert run(monkeypatch, fixture(prompt)).text == 'Slide body'


def test_duplicate_master_ids_and_lists_are_rejected(monkeypatch):
    f = File().edit({1: root(masters=persist(3, MASTER) + persist(4, MASTER)),
                     2: sheet()})
    with pytest.raises(InvalidDocumentError, match='duplicate'):
        run(monkeypatch, f)
    f = File().edit({1: container(1000, container(4080, b'', 1)
                                 + container(4080, b'', 1))})
    with pytest.raises(InvalidDocumentError, match='duplicate'):
        run(monkeypatch, f)


@pytest.mark.parametrize('target', [0, 0x80000099])
def test_title_master_enabled_broken_parent_fails_closed(monkeypatch, target):
    f = File().edit({1: root(masters=persist(3, TITLE_MASTER)),
                     2: sheet(master=TITLE_MASTER),
                     3: sheet(shape('Title artwork'), master=target, flags=1)})
    with pytest.raises(InvalidDocumentError, match='unresolved PPT master reference'):
        run(monkeypatch, f)


@pytest.mark.parametrize('target', [0, 0x80000099])
def test_title_master_disabled_broken_parent_is_not_followed(monkeypatch, target):
    f = File().edit({1: root(masters=persist(3, TITLE_MASTER)),
                     2: sheet(master=TITLE_MASTER),
                     3: sheet(shape('Title artwork'), master=target, flags=4)})
    assert run(monkeypatch, f).text == 'Title artwork'


def test_main_master_null_parent_with_objects_flag_is_terminal(monkeypatch):
    f = File().edit({1: root(), 2: sheet(),
                     3: sheet(shape('Main artwork'), master=0, flags=1, typ=1016)})
    assert run(monkeypatch, f).text == 'Main artwork'


def test_cached_blocks_are_charged_before_iteration():
    from legacy_office_parser.ppt import _Parser

    visits = []

    class TrackedBlocks(list):
        def __iter__(self):
            visits.append(len(self))
            return super().__iter__()

    parser = _Parser(b'', replace(Limits(), max_records=5))
    parser.master_cache[MASTER] = (TrackedBlocks([(1, 'A'), (1, 'B')]), 0)
    assert parser.master_text(MASTER) == [(1, 'A'), (1, 'B')]
    assert parser.records == 3  # one edge plus two block visits
    assert visits == [2]
    with pytest.raises(LimitExceededError, match='record'):
        parser.master_text(MASTER)
    # The next edge fits, but its two blocks do not. No iteration/allocation
    # of that cached batch may occur before rejecting it.
    assert visits == [2]


def test_many_empty_master_shapes_are_not_cached_or_revisited(monkeypatch):
    from legacy_office_parser import ppt

    count = 100
    objects = {1: root(b''.join(persist(10+i, 200+i) for i in range(count))),
               3: sheet(shape('') * 1000, master=0, flags=0, typ=1016)}
    objects.update({10+i: sheet() for i in range(count)})
    original = ppt._Parser.master_text
    emitted = []

    def checked(self, master_id):
        blocks = original(self, master_id)
        assert self.master_cache[MASTER][0] == []
        emitted.append(len(blocks))
        return blocks

    monkeypatch.setattr(ppt._Parser, 'master_text', checked)
    result = run(monkeypatch, File().edit(objects), replace(Limits(), max_records=20000))
    assert len(result.slides) == count
    assert all(s.text == '' for s in result.slides)
    assert emitted == [0] * count


# Original LibreOffice-generated CFB, unmodified; no private or external file.
# Provenance and regeneration: docs/PPT.md.
