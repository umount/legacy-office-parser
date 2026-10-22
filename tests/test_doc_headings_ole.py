"""Independent authored OLE headings: literal wire evidence and honest LO limits."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from legacy_office_parser import parse
from legacy_office_parser.models import Paragraph, Table

ROOT = Path(__file__).parent / "fixtures/doc_headings"
spec = importlib.util.spec_from_file_location("heading_fixture_probe", ROOT / "fixture.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_authored_source_is_reproducible_and_has_intended_outline_semantics():
    assert (ROOT / "authored.docx").read_bytes() == probe.source_bytes()
    assert probe.xml_levels(ROOT / "authored.docx") == probe.EXPECTED


def test_raw_doc_fixed_slots_and_custom_inheritance():
    styles, paragraphs = probe.binary(ROOT / "authored.doc")
    for level in (1, 2):
        assert styles[level]["sti"] == level
        assert styles[level]["kind"] == 1
        assert (0x2640, bytes([level - 1])) in styles[level]["ops"]
    inherited, direct = (
        paragraphs["Inherited heading specimen"],
        paragraphs["Direct body override specimen"],
    )
    assert inherited[0] == direct[0] >= 15
    style = styles[inherited[0]]
    assert style["sti"] == 0xFFE and style["base"] == 1
    assert all(op != 0x2640 for op, arg in style["ops"])
    assert all(op != 0x2640 for op, arg in inherited[1])
    assert (0x2640, b"\x09") in direct[1]
    custom = styles[paragraphs["Custom body style specimen"][0]]
    assert custom["sti"] == 0xFFE and custom["base"] == 1
    assert (0x2640, b"\x09") in custom["ops"]


def test_raw_doc_direct_outline_and_table_header_ownership():
    styles, paragraphs = probe.binary(ROOT / "authored.doc")
    assert set(paragraphs) == set(probe.EXPECTED)
    assert paragraphs["Ordinary body specimen"][0] == 0
    style, ops = paragraphs["Direct outline three specimen"]
    assert style == 0 and (0x2640, b"\x02") in ops
    assert paragraphs["Heading one specimen"][0] == 1
    assert paragraphs["Heading two specimen"][0] == 2
    style, ops = paragraphs["Cell heading specimen"]
    assert style == 2 and (0x2416, b"\x01") in ops
    assert paragraphs["Header heading specimen"][0] == 2


def test_parser_headings_match_source_and_binary_including_cell():
    doc = parse(ROOT / "authored.doc")
    got = {}

    def walk(blocks):
        for block in blocks:
            if isinstance(block, Paragraph):
                if block.text:
                    assert block.text not in got
                    got[block.text] = block.heading_level
            elif isinstance(block, Table):
                for row in block.rows:
                    for cell in row:
                        walk(cell.blocks)

    walk(doc.blocks)
    assert got == {
        text: level for text, level in probe.EXPECTED.items() if text != "Header heading specimen"
    }
    assert doc.headers_footers.count("Header heading specimen") == 1
    for text in probe.EXPECTED:
        assert doc.text.count(text) == 1


def test_header_heading_has_structured_metadata_without_duplicate_projection():
    doc = parse(ROOT / "authored.doc")
    blocks = doc.story_blocks.get("headers_footers", [])
    matches = [
        p for p in blocks if isinstance(p, Paragraph) and p.text == "Header heading specimen"
    ]
    assert len(matches) == 1
    assert matches[0].heading_level == 2
    assert doc.text.count("Header heading specimen") == 1


def test_saved_lo_readback_records_inheritance_loss_explicitly():
    expected = probe.EXPECTED | {"Inherited heading specimen": None}
    assert probe.xml_levels(ROOT / "readback/authored.docx") == expected


@pytest.mark.skipif(
    os.environ.get("OFFICE_CORPUS_LIBREOFFICE") != "1", reason="opt-in LibreOffice oracle"
)
def test_live_lo_readback_matches_supported_cases(tmp_path):
    office = shutil.which("libreoffice")
    if office is None:
        pytest.skip("LibreOffice unavailable")
    subprocess.run(
        [
            office,
            "-env:UserInstallation=" + (tmp_path / "profile").as_uri(),
            "--headless",
            "--convert-to",
            "docx:Office Open XML Text",
            "--outdir",
            str(tmp_path),
            str(ROOT / "authored.doc"),
        ],
        check=True,
        timeout=60,
        capture_output=True,
    )
    got = probe.xml_levels(tmp_path / "authored.docx")
    # LO 7.4 loses this inherited outline. A newer version may preserve it;
    # neither outcome is represented as proof against the stored DOC hierarchy.
    assert got.pop("Inherited heading specimen") in (None, 1)
    assert got == {k: v for k, v in probe.EXPECTED.items() if k != "Inherited heading specimen"}
