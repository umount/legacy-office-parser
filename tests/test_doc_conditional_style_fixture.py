"""Wire proof and observational LO evidence; no conditional runtime implementation."""

from pathlib import Path
import hashlib
import importlib.util
import json
import struct

import pytest
from test_doc_table_styles import streams, part, styles

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "tests/fixtures/doc_conditional_styles"


@pytest.mark.parametrize("mode,flags", [("disabled", 0x600), ("header", 0x620), ("corner", 0x720)])
def test_authored_conditional_wire_fixture(mode, flags):
    spec = importlib.util.spec_from_file_location(
        "conditional_fixture_generator", DIR / "generate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = DIR / (mode + ".doc")
    assert module.generate(mode) == module.generate(mode) == path.read_bytes()
    data = streams(path)
    source = streams(ROOT / "tests/fixtures/ordinary_table.doc")
    begin, end = struct.unpack_from("<II", source["WordDocument"], 24)
    assert data["WordDocument"][begin:end] == source["WordDocument"][begin:end]
    records = styles(data)
    assert records[:16] == styles(source)
    # Both conditions sit in CHPX, never in TAPX/PCnf. No unconditional vanish.
    raw = records[16]
    at = 12 + 2 * (struct.unpack_from("<H", raw, 10)[0] + 1)
    groups = []
    for _ in range(3):
        n = struct.unpack_from("<H", raw, at)[0]
        groups.append(raw[at + 2 : at + 2 + n])
        at += 2 + n + (n & 1)
    assert groups == [b"", b"", bytes.fromhex("85ca0501003c080185ca0500013c0800")]
    plc = part(data, 13)
    count = (len(plc) - 4) // 8
    row_groups = []
    for i in range(count):
        page = struct.unpack_from("<I", plc, 4 * (count + 1 + i))[0]
        fkp = data["WordDocument"][page * 512 : (page + 1) * 512]
        n = fkp[511]
        for j in range(n):
            offset = fkp[4 * (n + 1) + 13 * j] * 2
            if not offset:
                continue
            size = fkp[offset]
            start, length = (
                (offset + 1, size * 2 - 1) if size else (offset + 2, fkp[offset + 1] * 2)
            )
            group = fkp[start + 2 : start + length]
            if b"\x08\xd6" in group:
                row_groups.append(group)
    assert len(row_groups) == 3
    assert all(g.endswith(struct.pack("<HHHhH", 0x563A, 17, 0x740A, -1, flags)) for g in row_groups)


def test_lo_negative_result_is_not_misreported_as_spec_success():
    report = json.loads((DIR / "lo-comparison.json").read_text())
    for mode, item in report["files"].items():
        assert item["sha256"] == hashlib.sha256((DIR / (mode + ".doc")).read_bytes()).hexdigest()
        assert not any(
            item[key] for key in ("PrintHiddenText", "ShowHiddenCharacters", "ShowHiddenParagraphs")
        )
        assert item["stored_table_text"][0]["A1"] == "Key"
        assert "Key" not in item["pdf_visible_text"]
        assert "Value" in item["pdf_visible_text"]
    assert (
        report["files"]["header"]["pdf_visible_text"]
        == report["files"]["disabled"]["pdf_visible_text"]
    )
