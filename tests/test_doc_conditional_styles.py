"""Independent cell text oracles for the intentionally narrow CCnf subset."""

from pathlib import Path
import struct
import pytest
from legacy_office_parser import parse_doc, Limits, InvalidDocumentError, LimitExceededError
from legacy_office_parser.models import Table
from test_doc import IN, ROW, definition, fixture, parse, sprm, u16
from test_doc_styles import stylesheet, style
from test_doc_table_styles import tistd, vanish


def cnf(condition, value):
    return sprm(0xCA85, bytes([5]) + u16(condition) + vanish(value))


def table_style(index=16, base=0xFFF, chpx=b"", tapx=b"", papx=b""):
    groups = (tapx, papx, chpx)
    raw = struct.pack("<5H", 0x1FFE, base << 4 | 3, index << 4 | 3, 0, 0)
    raw += u16(1) + b"S\0\0\0"
    for group in groups:
        raw += u16(len(group)) + group + b"\0" * (len(group) & 1)
    return u16(len(raw)) + raw


def data(
    rows=3,
    cols=3,
    *,
    chpx=None,
    look=0x620,
    tapx=b"",
    papx=b"",
    row_extra=None,
    cell_extra=None,
    flags=None,
    edges=None,
    para_chpx=b"",
):
    text, props = "", []
    for r in range(rows):
        for c in range(cols):
            text += f"{r}{c}\7"
            props.append(IN + (cell_extra(r, c) if cell_extra else b""))
        text += "\7"
        extra = row_extra(r) if row_extra else b""
        props.append(
            ROW
            + definition(flags or [0] * cols, edges)
            + tistd(16)
            + struct.pack("<HhH", 0x740A, -1, look)
            + extra
        )
    records = [style(0, chpx=para_chpx)] + [b"\0\0"] * 15
    records += [table_style(chpx=cnf(1, 1) if chpx is None else chpx, tapx=tapx, papx=papx)]
    return stylesheet(fixture([(text, True)], props=props), records)


def texts(doc):
    return [
        [[cell.text for cell in row] for row in block.rows]
        for block in doc.blocks
        if isinstance(block, Table)
    ]


@pytest.mark.parametrize(
    "condition,look,hidden",
    [
        (1, 0x620, {(0, 0), (0, 1), (0, 2)}),
        (2, 0x640, {(2, 0), (2, 1), (2, 2)}),
        (4, 0x680, {(0, 0), (1, 0), (2, 0)}),
        (8, 0x700, {(0, 2), (1, 2), (2, 2)}),
        (256, 0x720, {(0, 2)}),
        (512, 0x6A0, {(0, 0)}),
        (1024, 0x740, {(2, 2)}),
        (2048, 0x6C0, {(2, 0)}),
    ],
)
def test_each_edge_corner_option_and_disabled(monkeypatch, condition, look, hidden):
    for options, selected in ((look, hidden), (0x600, set())):
        result = parse(monkeypatch, data(chpx=cnf(condition, 1), look=options))
        assert texts(result) == [
            [["" if (r, c) in selected else f"{r}{c}" for c in range(3)] for r in range(3)]
        ]


@pytest.mark.parametrize(
    "mode,first",
    [
        ("disabled", ["", "Value", "Примечание"]),
        ("header", ["", "", ""]),
        ("corner", ["", "", "Примечание"]),
    ],
)
def test_authored_real_cfb(mode, first):
    path = Path(__file__).parent / "fixtures/doc_conditional_styles" / (mode + ".doc")
    assert texts(parse_doc(path)) == [
        [first, ["alpha beta", "", "два слова"], ["", "42", "English and русский"]]
    ]


@pytest.mark.parametrize("vertical", [False, True])
@pytest.mark.parametrize("size", [1, 2, 3])
@pytest.mark.parametrize("even", [False, True])
def test_explicit_band_sizes_and_polarity(monkeypatch, vertical, size, even):
    op = 0x3489 if vertical else 0x3488
    condition = (32 if even else 16) if vertical else (128 if even else 64)
    look = 0x200 if vertical else 0x400
    d = data(rows=7, cols=7, chpx=cnf(condition, 1), look=look, tapx=sprm(op, size))
    result = texts(parse(monkeypatch, d))[0]
    assert result == [
        ["" if (((c if vertical else r) // size) % 2 == int(even)) else f"{r}{c}" for c in range(7)]
        for r in range(7)
    ]
    assert (
        texts(parse(monkeypatch, data(chpx=cnf(condition, 1), look=0x600, tapx=sprm(op, size))))[0][
            0
        ][0]
        == "00"
    )


def test_absent_band_size_does_not_invent_one(monkeypatch):
    assert texts(parse(monkeypatch, data(chpx=cnf(64, 1) + cnf(16, 1), look=0)))[0][0] == [
        "00",
        "01",
        "02",
    ]


def test_header_prefix_band_exclusion_and_isolated_flag(monkeypatch):
    result = texts(
        parse(
            monkeypatch,
            data(
                rows=5,
                cols=1,
                look=0x420,
                chpx=cnf(64, 1),
                tapx=sprm(0x3488, 1),
                row_extra=lambda r: sprm(0x3404, 1) if r in (0, 1, 4) else b"",
            ),
        )
    )[0]
    assert result == [["00"], ["10"], [""], ["30"], [""]]


def test_first_column_band_count_exclusion(monkeypatch):
    result = texts(
        parse(monkeypatch, data(rows=1, cols=4, look=0x280, chpx=cnf(16, 1), tapx=sprm(0x3489, 1)))
    )[0]
    assert result == [["00", "", "02", ""]]


def test_priority_not_wire_order_and_single_cell_ties(monkeypatch):
    # Last-wire column hide must lose to row show and corner hide.
    ops = (
        cnf(512, 1)
        + cnf(1, 0)
        + cnf(4, 1)
        + cnf(2, 1)
        + cnf(8, 1)
        + cnf(256, 0)
        + cnf(2048, 0)
        + cnf(1024, 0)
    )
    result = texts(parse(monkeypatch, data(chpx=ops, look=0x7E0)))[0]
    assert result[0] == ["", "01", "02"]
    assert texts(parse(monkeypatch, data(rows=1, cols=1, chpx=ops, look=0x7E0))) == [[[""]]]


@pytest.mark.parametrize(
    "extra", [sprm(0x940E, u16(100)), sprm(0x7469, b"\1\0\0\0"), sprm(0x560B, u16(1))]
)
def test_identity_partition_restarts_header(monkeypatch, extra):
    result = parse(monkeypatch, data(rows=3, cols=1, row_extra=lambda r: extra if r == 0 else b""))
    assert texts(result) == [[[""]], [[""], ["20"]]]


def test_first_cell_frame_partition_restarts_header(monkeypatch):
    result = parse(
        monkeypatch, data(cols=1, cell_extra=lambda r, c: sprm(0x841A, u16(100)) if r == 0 else b"")
    )
    assert texts(result) == [[[""]], [[""], ["20"]]]


def test_later_cell_frame_does_not_split(monkeypatch):
    result = parse(
        monkeypatch,
        data(cell_extra=lambda r, c: sprm(0x841A, u16(100)) if (r, c) == (1, 1) else b""),
    )
    assert len(texts(result)) == 1
    assert texts(result)[0][1] == ["10", "11", "12"]


@pytest.mark.parametrize("kind", ["merge", "grid", "pcnf", "tcnf", "direction", "incomplete"])
def test_unproven_context_retains_unconditional(monkeypatch, kind):
    kwargs = {}
    if kind == "merge":
        kwargs["flags"] = [2, 1, 0]
    if kind == "grid":
        kwargs["row_extra"] = lambda r: definition([0, 0, 0], [0, 110, 200, 300]) if r == 1 else b""
        # Unequal grids now support row-only rules; column ownership remains unproven.
        kwargs["chpx"] = cnf(1, 1) + cnf(4, 1)
    if kind == "pcnf":
        kwargs["papx"] = sprm(0xC666, b"\2\1\0")
    if kind == "tcnf":
        kwargs["tapx"] = sprm(0xD66A, b"\2\1\0")
    if kind == "direction":
        kwargs["row_extra"] = lambda r: sprm(0x560B, u16(2))
    d = data(**kwargs)
    if kind == "incomplete":
        # The final TTP becomes an ordinary cell; prior rows' last-row context is unknown.
        # Rebuild transport instead of editing arbitrary binary offsets.
        d = stylesheet(
            fixture(
                [("00\7\7tail\7", True)],
                props=[
                    IN,
                    ROW + definition([0]) + tistd(16) + struct.pack("<HhH", 0x740A, -1, 0x620),
                    IN,
                ],
            ),
            [style(0)] + [b"\0\0"] * 15 + [table_style(chpx=cnf(1, 1))],
        )
    result = parse(monkeypatch, d)
    assert texts(result)[0][0][0] == "00"
    assert any("no proven stable rectangular" in w for w in result.warnings)


def test_paragraph_direct_override(monkeypatch):
    assert texts(parse(monkeypatch, data(para_chpx=vanish(0))))[0][0] == ["00", "01", "02"]
    from test_doc_fidelity import add_chpx

    d = data(rows=1, cols=1)
    add_chpx(d, [1024, 1026, 1028], [vanish(0), None])
    assert texts(parse(monkeypatch, d)) == [[["00"]]]


@pytest.mark.parametrize(
    "bad",
    [
        sprm(0xCA85, b"\2\3\0"),
        sprm(0xCA85, b"\5\1\0" + vanish(2)),
        sprm(0xCA85, b"\5\1\0" + sprm(0x2416, 1)),
        sprm(0xCA85, b"\5\1\0\x85\xca\0"),
    ],
)
def test_bad_conditional_operations(monkeypatch, bad):
    with pytest.raises(InvalidDocumentError):
        parse(monkeypatch, data(chpx=bad))


@pytest.mark.parametrize("size", [0, 4, 255])
def test_bad_bands(monkeypatch, size):
    with pytest.raises(InvalidDocumentError, match="band"):
        parse(monkeypatch, data(tapx=sprm(0x3488, size)))


def test_record_limits(monkeypatch):
    with pytest.raises(LimitExceededError, match="record"):
        parse(monkeypatch, data(), Limits(max_records=20))


def test_horizontal_then_vertical_then_column_then_row(monkeypatch):
    ops = cnf(64, 1) + cnf(16, 0) + cnf(4, 1) + cnf(1, 0)
    result = texts(
        parse(
            monkeypatch,
            data(rows=3, cols=3, look=0xA0, chpx=ops, tapx=sprm(0x3488, 1) + sprm(0x3489, 1)),
        )
    )[0]
    assert result == [["00", "01", "02"], ["", "11", ""], ["", "21", "22"]]


@pytest.mark.parametrize("direction", [0x560B, 0x5664])
def test_rtl_uses_logical_cell_order(monkeypatch, direction):
    result = texts(
        parse(
            monkeypatch,
            data(rows=1, look=0x680, chpx=cnf(4, 1), row_extra=lambda r: sprm(direction, u16(1))),
        )
    )[0]
    assert result == [["", "01", "02"]]


def test_nested_tables_have_own_positions(monkeypatch):
    from test_doc_nested import streams, cell, row

    select = tistd(16) + struct.pack("<HhH", 0x740A, -1, 0x620)
    rt, rp = row(2)
    ot, op = row(1)
    d = streams(
        cell(2, "inner0"),
        (rt, rp + select),
        cell(2, "inner1"),
        (rt, rp + select),
        cell(1, "outer"),
        (ot, op + select),
    )
    stylesheet(d, [style(0)] + [b"\0\0"] * 15 + [table_style(chpx=cnf(1, 1))])
    doc = parse(monkeypatch, d)
    outer = doc.blocks[0].rows[0][0]
    inner = outer.blocks[0]
    assert [[c.text for c in r] for r in inner.rows] == [[""], ["inner1"]]
    assert "outer" in outer.text
    assert any("no proven stable rectangular" in w for w in doc.warnings)


@pytest.mark.parametrize("reason", ["grid", "bookmark", "frame"])
def test_unknown_conditional_note_visibility(monkeypatch, reason):
    from legacy_office_parser.doc import _Doc
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc

    main, body = "\x02\7\7", "note\r\r"
    rowprops = (
        ROW
        + definition([0], [0, 0] if reason == "grid" else [0, 100])
        + tistd(16)
        + struct.pack("<HhH", 0x740A, -1, 0x620)
    )
    d = stylesheet(
        fixture(
            [(main + body, True)],
            props=[IN, rowprops, b"", b""],
            counts=[len(main), len(body), 0, 0, 0, 0, 0],
        ),
        [style(0)]
        + [b"\0\0"] * 15
        + [table_style(chpx=cnf(1, 1), papx=sprm(0x841A, u16(100)) if reason == "frame" else b"")],
    )
    add_chpx(d, [1024, 1024 + len(main + body)], [sprm(0x0855, 1)])
    append_table_part(d, 2, reference_plc([0]))
    append_table_part(d, 3, text_plc([0, len(body) - 1]))
    if reason == "bookmark":
        original = _Doc._fib

        def fib(self):
            original(self)
            pairs = bytearray(self.pairs).ljust(144 * 8, b"\0")
            struct.pack_into("<II", pairs, 137 * 8, 0, 1)
            self.pairs = memoryview(pairs)

        monkeypatch.setattr(_Doc, "_fib", fib)
    result = parse(monkeypatch, d)
    assert result.notes[0].visibility == ["unknown"]
    assert result.footnotes == "note\n"
    assert any("no proven stable rectangular" in w for w in result.warnings)


def test_known_conditional_note_hidden(monkeypatch):
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc

    main, body = "\x02\7\7", "note\r\r"
    d = stylesheet(
        fixture(
            [(main + body, True)],
            props=[
                IN,
                ROW + definition([0]) + tistd(16) + struct.pack("<HhH", 0x740A, -1, 0x620),
                b"",
                b"",
            ],
            counts=[len(main), len(body), 0, 0, 0, 0, 0],
        ),
        [style(0)] + [b"\0\0"] * 15 + [table_style(chpx=cnf(1, 1))],
    )
    add_chpx(d, [1024, 1024 + len(main + body)], [sprm(0x0855, 1)])
    append_table_part(d, 2, reference_plc([0]))
    append_table_part(d, 3, text_plc([0, len(body) - 1]))
    assert parse(monkeypatch, d).notes[0].visibility == ["hidden"]


def test_conditional_work_bounded_by_cells_not_characters(monkeypatch):
    from legacy_office_parser.doc import _Doc

    original = _Doc.clean
    counts = []

    def clean(self, *args, **kwargs):
        counts.append(self.budget.records)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_Doc, "clean", clean)
    parse(monkeypatch, data())
    threshold = counts[0]
    counts.clear()
    with pytest.raises(LimitExceededError, match="record"):
        parse(monkeypatch, data(), Limits(max_records=threshold - 1))
    assert not counts


def test_style_depth_limit(monkeypatch):
    d = data()
    stylesheet(
        d,
        [style(0)]
        + [b"\0\0"] * 15
        + [table_style(16, 17, cnf(1, 1)), table_style(17, 18), table_style(18)],
    )
    with pytest.raises(LimitExceededError, match="depth"):
        parse(monkeypatch, d, Limits(max_depth=2))


def test_unknown_neighbor_direction_cannot_prove_last_row(monkeypatch):
    result = parse(
        monkeypatch,
        data(
            rows=2,
            cols=1,
            look=0x640,
            chpx=cnf(2, 1),
            row_extra=lambda r: sprm(0x560B, u16(2)) if r else b"",
        ),
    )
    assert texts(result) == [[["00"]], [["10"]]]
    assert any("no proven stable rectangular" in w for w in result.warnings)


def test_child_condition_overrides_parent_and_style_cache_separates_positions(monkeypatch):
    d = data()
    stylesheet(
        d,
        [style(0)]
        + [b"\0\0"] * 15
        + [table_style(16, 17, cnf(1, 0)), table_style(17, chpx=cnf(1, 1))],
    )
    assert texts(parse(monkeypatch, d))[0] == [
        ["00", "01", "02"],
        ["10", "11", "12"],
        ["20", "21", "22"],
    ]


def test_unconditional_hide_retained_when_conditional_show_is_unproven(monkeypatch):
    result = parse(
        monkeypatch, data(rows=1, cols=1, chpx=vanish(1) + cnf(1, 0), papx=sprm(0x841A, u16(100)))
    )
    assert texts(result) == [[[""]]]
    assert any("no proven stable rectangular" in w for w in result.warnings)


def test_auxiliary_story_does_not_extend_main_table(monkeypatch):
    main, body = "A\7\7", "B\7\7"
    rp = ROW + definition([0]) + tistd(16) + struct.pack("<HhH", 0x740A, -1, 0x620)
    d = stylesheet(
        fixture(
            [(main + body, True)],
            props=[IN, rp, IN, rp],
            counts=[len(main), len(body), 0, 0, 0, 0, 0],
        ),
        [style(0)] + [b"\0\0"] * 15 + [table_style(chpx=cnf(1, 1))],
    )
    result = parse(monkeypatch, d)
    assert texts(result) == [[[""]]]
    assert result.story_blocks["footnotes"][0].rows[0][0].text == ""


@pytest.mark.parametrize('operand', [128, 129])
def test_relative_conditional_toggle_is_explicitly_unproven(monkeypatch, operand):
    result = parse(monkeypatch, data(rows=1, cols=1, chpx=cnf(1, operand)))
    assert texts(result) == [[['00']]]
    assert any('no proven stable rectangular' in w for w in result.warnings)


@pytest.mark.parametrize("boundary", ["position", "direction", "frame"])
@pytest.mark.parametrize("note_at", ["before", "after", "future"])
def test_nested_row_uncertainty_survives_boundary_without_tainting_previous(
    monkeypatch, boundary, note_at
):
    from test_doc_nested import cell, paragraph, row
    from test_doc_fidelity import add_chpx, append_table_part
    from test_doc_notes import reference_plc, text_plc

    select = tistd(16) + struct.pack("<HhH", 0x740A, -1, 0x680)
    row_change = {
        "position": sprm(0x940E, u16(100)),
        "direction": sprm(0x560B, u16(1)),
        "frame": b"",
    }[boundary]
    frame = sprm(0x841A, u16(100)) if boundary == "frame" else b""
    rt, rp = row(1)
    before, bp = paragraph(1, "outer-before" + ("\x02" if note_at == "before" else ""))
    future, fp = cell(1, "future" + ("\x02" if note_at == "future" else ""))
    parts = [
        cell(1, "previous"), (rt, rp + select),
        (before, bp + frame), cell(2, "inner"), row(2),
        cell(1, "outer-after" + ("\x02" if note_at == "after" else "")),
        (rt, rp + select + row_change),
        (future, fp + frame), (rt, rp + select + row_change),
        cell(1, "recovered"), (rt, rp + select),
    ]
    main = "".join(text for text, _ in parts)
    body = "note\r\r"
    d = stylesheet(
        fixture(
            [(main + body, True)],
            props=[p for _, p in parts] + [b"", b""],
            counts=[len(main), len(body), 0, 0, 0, 0, 0],
        ),
        [style(0)] + [b"\0\0"] * 15 + [table_style(chpx=cnf(4, 1))],
    )
    add_chpx(d, [1024, 1024 + len(main + body)], [sprm(0x0855, 1)])
    append_table_part(d, 2, reference_plc([main.index("\x02")]))
    append_table_part(d, 3, text_plc([0, len(body) - 1]))
    result = parse(monkeypatch, d)
    assert texts(result) == [
        [[""]], [["outer-before\ninner\nouter-after"], ["future"]], [[""]]
    ]
    assert result.notes[0].visibility == ["unknown"]
    assert any("no proven stable rectangular" in w for w in result.warnings)
