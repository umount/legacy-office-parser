# Original synthetic legacy Office fixtures

All text and document structures in this directory were authored specifically for
legacy-office-parser on 2026-10-21. They are synthetic test data, not private user
documents, customer documents, downloaded samples, or copies of personal files.
No personal temporary files were read or copied. The small PPTX uses python-pptx's
bundled blank presentation package for standard Office layout/master parts; all
slide and notes content is original.

## Contents

- `ordinary_table.doc`: English/Cyrillic paragraphs around an ordinary 3 × 3
  table. Includes an interior empty cell, a leading empty cell, and multiword
  English and Cyrillic cells. Empty cells must not shift later columns.
- `merged_table.doc`: separate 3-column table with a two-column horizontal merge
  in its first row and a two-row vertical merge in its first column. Expectations
  preserve covered coordinates, distinguish empty cells from covered cells, and
  keep paragraphs before and after the table in document order.
- `slides_notes.ppt`: three slides. First has a real title placeholder and a
  bilingual body; second is completely blank; third has a title/body and notes.
  Only the third slide has authored notes. Its notes page intentionally omits
  slide-image and slide-number placeholders so those cannot contaminate notes.
- `sources/*.odt`: original hand-authored XML ZIP source documents.
- `sources/slides_notes.pptx`: original programmatically authored OOXML source.
- `*.expected.json`: independently hand-authored semantic expectations using the
  public `Document`, `Paragraph`, `Table`, `Cell`, and `Slide` dataclass fields.
  These files are never generated from parser output or overwritten by the tool.

## Regeneration

Run from the project root using Python with `python-pptx` installed:

```sh
python tools/generate_fixtures.py
```

The generator invokes `/usr/bin/libreoffice --headless` with `MS Word 97` and
`MS PowerPoint 97` export filters. Initial binaries were produced by LibreOffice
7.4.7.2, 40(Build:2). It uses a unique temporary `UserInstallation` profile,
stages each output in its own temporary directory, validates the OLE magic,
and enforces a 45-second timeout per conversion. On timeout, only the spawned
process group is terminated. It never attaches to or terminates another user's
LibreOffice session. `--libreoffice` and `--timeout` override these defaults.

Generated binary metadata and OOXML ZIP timestamps may vary across runs or
LibreOffice versions. Semantic equivalence is the reproducibility target, not
byte-for-byte binary equality. Tests use checked-in binaries and need neither
LibreOffice nor python-pptx at runtime.

## Regression contract and verification

Run:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -p no:cacheprovider tests/test_fixture_corpus.py -q
```

Tests call only public `legacy_office_parser.parse_doc(path)` and
`legacy_office_parser.parse_ppt(path)` and compare dataclasses against the
hand-authored expectations. Exactly empty layout paragraphs are ignored;
whitespace, multiword cells, empty/covered cells, slide positions, title/body
separation, and notes are not normalized away. Warning wording is not part of
this content contract: tests require string warnings but allow implementation
capability warnings (including LibreOffice extension-record diagnostics).
The JSON `warnings: []` fields are neutral placeholders, not an assertion that
these legacy files must produce no diagnostics.

Independent LibreOffice DOC → ODT round-trip inspection confirmed all ordinary
cells and both merge spans, including covered coordinates. PPT source correction
used native OOXML title placeholders, avoiding an ODF exporter behavior that
converted title frames to generic drawing text. A notes slide-number placeholder
was also removed from the source because LibreOffice exported it as a literal
asterisk. The final PPT passes all hand-authored slide and notes expectations.

All six corpus checks pass, including horizontal and vertical merged cells.
