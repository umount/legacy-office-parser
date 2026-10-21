# DOC extraction style profile

Scope: Word 97–2003 STSH paragraph/character style inheritance for text extraction.
This is not full DOC support, Word layout, a table-style engine, or a revision
acceptance engine.

## Specification findings that constrain the implementation

Primary references (Microsoft MS-DOC):

- [STSH, 2.9.271](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/c8ee0f39-02c3-4caa-b27a-6a97600130fe): indexed style records and legal empty fixed styles.
- [Stshif](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/0e246123-e907-4ad1-9dfc-558512e2b052) and [StdfBase](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/df0f4654-071d-442f-8563-752d7e0285ef): record count, 10/18-byte headers, style kind and base index.
- [STD](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/dd73d580-cce7-445f-b692-3421060b9682) and [LPUpxChpx](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/15038623-de68-452c-9e1a-7121b3ae5624): name boundaries, UPX lengths and alignment.
- [Style properties, 2.4.6.5](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/9258b41c-ff0a-4c96-a3a9-610664dabbeb) and [formatting order, 2.4.6.6](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417).
- [UpxPapx](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/659f448a-473a-44c6-8b69-a25984af3645) and [UpxChpx](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/0188ecda-b590-4cb4-bb95-e76a47a9a2e2): style property restrictions.
- [Character properties, 2.6.1](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/7022285b-9621-42e9-ad4d-4e02c115ef18), [ToggleOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/bc4ca98b-68ca-49dc-a091-1460e42d781e), and [Prm0](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/35226a0b-9038-4427-83c2-3830a8554267).

Table membership, TTP, nesting depth and inner-cell flags are structural direct
properties preserved across paragraph style changes. UpxPapx prohibits those
preserved properties. A synthetic style carrying PFInTable/PFTtp is therefore
not evidence of a real missing inheritance feature. Such records are rejected,
not used to invent a table. Likewise CFSpec, CSymbol, CFRMarkDel and CFFldVanish
are not valid inheritable UpxChpx properties. They are direct properties preserved
across character style changes. CFVanish is a valid inherited property.

## Implemented extraction behavior

- Read the active stylesheet at FIB pair 1 (`fcStshf`), not pair 0
  (`fcStshfOrig`). Parse bounded LPStd records, 10/18-byte Stdf layouts, Xstz
  name boundaries, padded UPX blocks and paragraph-style istd prefixes.
  Names are neither emitted nor used to guess semantics.
- Retain PAPX istd. Resolve paragraph styles from the paragraph-mark piece,
  including split compressed/UTF-16 pieces. Direct PIstd changes the selected
  paragraph style while retaining existing table flags, grids and merge data.
- Resolve CFVanish through paragraph and character basedOn chains, with child
  overrides, explicit zero, and parent-relative 0x80/0x81 operands. Character
  style selection through CIstd resets visibility to paragraph plus selected
  character style. CPlain restores paragraph visibility.
- Apply direct CHPX then piece PRC/Prm0 overrides. CFVanish, CFRMarkDel and
  CFFldVanish suppress text, including ordinary characters and auxiliary stories.
  Insertions remain visible; strikethrough is not treated as deletion.
- Preserve direct CFSpec, CSymbol, deleted and field-hidden state across
  CIstd/CPlain. Resolve direct style-relative CFSpec against its permitted style
  default when STSH exists. Retain the previous explicit warning/fallback for
  relative CFSpec when STSH is absent.
- Handle the CFVanish part of CMajority, including the default character-style
  guard and comparison before reset. Other CMajority visual properties are not
  represented by this extraction model.
- Keep field delimiters balanced before filtering their stored result text.
  Hidden/deleted paragraph and cell marks retain structural boundaries and issue
  a specific diagnostic. This does not merge paragraphs or delete table rows.
- Retain pre-existing direct table property support: membership, row ends,
  depth/deltas, inner flags, directions, explicit grids and merge flags. Own
  regression checks that hiding cell content does not shift its coordinate.

## Bounds and deliberately uncovered behavior

Stylesheet records, UPX blocks, decoded Prls and resolved chain nodes share the
existing record budget. Style walks are iterative and limited by max_depth.
Selected chains reject cycles, dangling/empty parents, and mismatched kinds.
Truncated structures raise structured parse errors. Resolved visibility is
cached by style/kind/incoming visibility; direct character evaluation caches only
its last context, avoiding a CP-sized property cache. Unused inheritance graphs
are not exhaustively validated.

This is a focused reader, not a complete MS-DOC validator. Unsupported visual
properties (fonts, size, emphasis, spacing, borders, etc.) are not represented.
Table/list style UPX records are structurally bounded but their formatting is not
applied. Conditional table styles, table/list style selection, numbering-derived
formatting, linked-style behavior, style revision history and full revision/move
acceptance remain uncovered. TIstd produces a table-style limitation warning.
Paragraph style permutations/increments and character style permutations raise
UnsupportedFormatError rather than silently choosing visibility from the wrong
style. Web-only hidden text, structured-document-tag hiding and style separators
are not equivalent to CFVanish and are not filtered by this profile.

Absent STSH remains tolerated for existing extraction callers using default
styles. Explicit non-default unresolved style references fail. Missing CHPX
coverage retains text with a coverage warning when a character bin exists.
Unconditional character-formatting/paragraph-inheritance warnings were removed;
an ordinary supported DOC may now have no warnings and CLI strict may return 0.

## Evidence and reproducibility

All new text is authored in `tests/test_doc_styles.py`. The synthetic stream
writer uses literal MS-DOC layouts and independently specified expected text.
The original LO fixture is generated in pytest tmp_path from minimal authored
OOXML, exported by LibreOffice with an isolated UserInstallation profile and a
45-second timeout. No binary fixture, converter code, or common tool is added to
the repository. Existing original ordinary/merged LO DOC fixtures independently
check that table coordinates and merge geometry are preserved.

Before/after evidence: loading the original `doc.py` into a test process failed
all seven selected synthetic cases (paragraph inheritance in both encodings,
character inheritance/reset, three direct visibility cases and styled table
content). The original parser also failed the authored LO fixture, emitting
paragraph-hidden, character-hidden and revision-deleted marker text. The new
parser yields only `KEEPTAIL`, `OVERRIDE`, `ANEWZ` as nonempty paragraphs.
These markers are authored fixture content, not private text.

Deterministic tests (no converter invocation):

```sh
.venv/bin/python -m pytest -q tests/test_doc_styles.py
.venv/bin/python -m ruff check src/legacy_office_parser/doc.py src/legacy_office_parser/_doc_styles.py tests/test_doc_styles.py
```

Live integration uses the existing corpus opt-in convention:

```sh
OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/python -m pytest -q tests/test_doc_styles.py
```

Ordinary test runs skip live integration unless the opt-in flag is set, even
when a LibreOffice executable is installed.

Validation results:

- DOC-focused deterministic run: **328 passed, 1 skipped**.
- Explicit live style run with `OFFICE_CORPUS_LIBREOFFICE=1`: **51 passed**.
- Ruff on the implementation and style tests: **passed**.
- Raw exported LO STSH retains real inheritance: character style 16 is based on
  15, paragraph style 23 on 22; the parents carry CFVanish=1 and both children
  have no own visibility operand. Thus the live fixture tests inheritance rather
  than merely direct formatting flattened by the exporter.
