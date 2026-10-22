"""Independent row-condition matrix and malformed boundary regressions."""

import itertools
import struct
import pytest
from test_doc import IN, ROW, definition, fixture, parse, sprm
from test_doc_conditional_rows import source, RAGGED, FALLBACK
from test_doc_conditional_styles import cnf, table_style
from test_doc_styles import style, stylesheet
from test_doc_table_styles import tistd, vanish


@pytest.mark.parametrize(
    "condition,top,bottom,size,show",
    list(
        itertools.product((1, 2, 64, 128), (False, True), (False, True), (1, 2, 3), (False, True))
    ),
)
def test_independent_row_oracle(monkeypatch, condition, top, bottom, size, show):
    rows = [
        (
            [f"R{r}X", ""] if r % 2 else [f"R{r}X"],
            [0, 100, 200] if r % 2 else [25, 175],
            [2, 1] if r % 2 else [0],
        )
        for r in range(5)
    ]
    flags = 0x400 | (0x20 if top else 0) | (0x40 if bottom else 0)
    raw = source(
        rows,
        look=flags,
        chpx=(vanish(1) if show else b"") + cnf(condition, 0 if show else 1),
        tapx=sprm(0x3488, size),
    )
    result = parse(monkeypatch, raw)
    for r in range(5):
        special_top = top and r == 0
        special_bottom = bottom and r == 4 and not special_top
        band = ((r - int(top)) // size) % 2
        selected = {
            1: special_top,
            2: special_bottom,
            64: not (special_top or special_bottom) and band == 0,
            128: not (special_top or special_bottom) and band == 1,
        }[condition]
        assert (f"R{r}X" in result.text) == (selected if show else not selected)
    assert not any(FALLBACK in w for w in result.warnings)


@pytest.mark.parametrize("shape", ["ragged", "merged"])
@pytest.mark.parametrize("show", [False, True])
def test_bad_depth_one_ttp_must_not_prove_context(monkeypatch, shape, show):
    rows = (
        RAGGED
        if shape == "ragged"
        else [(["A", ""], [0, 100, 200], [2, 1]), (["B", ""], [0, 100, 200], [2, 1])]
    )
    text, props = "", []
    for values, edges, flags in rows:
        for value in values:
            text += value + "\7"
            props.append(IN)
        text += "\r"  # Invalid: depth-one TTP must be U+0007, not CR.
        props.append(
            ROW + definition(flags, edges) + tistd(16) + struct.pack("<HhH", 0x740A, -1, 0x620)
        )
    data = stylesheet(
        fixture([(text, True)], props=props),
        [style(0)]
        + [b"\0\0"] * 15
        + [table_style(chpx=(vanish(1) if show else b"") + cnf(1, 0 if show else 1))],
    )
    result = parse(monkeypatch, data)
    assert ("A" in result.text) == (not show)
    assert any(FALLBACK in w for w in result.warnings)
