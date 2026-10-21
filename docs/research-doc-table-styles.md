# DOC unconditional table-style CFVanish

The reader applies inherited, unconditional hidden-text properties from the
innermost table row before paragraph and direct character formatting.

## Primary evidence

- [StkTableGRLPUPX, 2.9.270](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/1bf37486-85c7-469b-a817-6204bbb7ed32): table styles have TAPX, PAPX, CHPX groups in that order.
- [UpxChpx, 2.9.336](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/0188ecda-b590-4cb4-bb95-e76a47a9a2e2): CFVanish is not forbidden. Do not confuse it with prohibited CFSpecVanish or preserved CFFldVanish.
- [Character properties, 2.6.1](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/7022285b-9621-42e9-ad4d-4e02c115ef18): CFVanish is hidden-text formatting; explicit 0 overrides hiding.
- [Determining formatting, 2.4.6.6](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417): use the innermost containing row's table style, before paragraph-style and direct character formatting.
- [StdfBase](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/df0f4654-071d-442f-8563-752d7e0285ef): table kind 3, three UPX groups, parent index and bounded style indices.

## Original fixture

`tools/generate_doc_table_style_fixture.py` derives only the authored
`tests/fixtures/ordinary_table.doc`. It uses the generic regular-CFB writer and
copies the inline PAPX rebuild approach, without importing production parser code.
Original text FCs, paragraph styles and explicit 3x3 grid remain unchanged.
New styles 16/17 are a table parent/child; every row directly selects style 17.
No external PAPX fallback or PGPInfo is introduced.

Variants:

- `visible.doc`: parent/child have no hidden operation.
- `inherited.doc`: parent has CFVanish=1, child inherits.
- `child_show.doc`: same parent; child explicitly sets CFVanish=0.

Every variant has direct CFVanish=1 on `Key` and direct CFVanish=0 on
`alpha beta`. These isolate direct hiding and direct show override from inheritance.
All stored words remain present. Spec-derived visible cells for inherited.doc are
three rows of three cells, with only A2 = `alpha beta` nonempty. Surrounding body
paragraphs remain visible. Geometry and cell boundaries must survive hidden text.

## Independent LibreOffice result

LibreOffice 7.4.7.2 40(Build:2), isolated fresh profile, UNO import read-only,
MacroExecMode.NEVER_EXECUTE, UpdateDocMode=0. Explicitly disabled
ShowHiddenCharacters, ShowHiddenParagraphs and PrintHiddenText. Exported PDF and
read its rendered text using pdftotext -layout; UNO cell strings separately record
stored text. Raw DOCX XML is NOT used as a visible-text oracle.

All three variants retain all stored cell strings. All three PDF exports hide
`Key`, show `alpha beta`, and also show `Value`, `Примечание`, `два слова`, `42`,
and `English and русский`. Thus direct-hidden control works, but this LO importer
DOES NOT corroborate inherited table-style hidden semantics. This is a documented
interop discrepancy, not an independently confirmed visible-output success.
No Word comparison has been performed. Binary invariants and primary spec support
the API expectation; LO does not establish its correctness by itself.

Reproduction: generate with the project venv; start a fresh headless LO profile
with `--accept='socket,host=localhost,port=20171;urp;StarOffice.ComponentContext'`;
run `/usr/bin/python3 tests/fixtures/doc_table_styles/compare_lo.py` (system UNO).
PDFs are temporary; `lo-comparison.json` records exact text/settings/input hashes.
The fixture test originally used strict xfail for missing inherited visibility.
After the row-context integration passed through the real public API, the xfail
was removed. This does not change the recorded LibreOffice discrepancy.

### UPX and TTlp recheck

The authored records have kind=3, cupx=3, TAPX/PAPX/CHPX order, matching bchUpe,
unique names, valid parent/next indices, and lengths excluding even-byte padding.
The empty table PAPX has no paragraph-style istd (UpxPapx describes that field as
optional and as the paragraph-style index); the empty TAPX introduces no prohibited
structural properties. The ordinary source styles/text are unchanged.
[LPUpxPapx](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/44774bb4-730b-4a46-8002-8608ae2e9525)
confirms the length/padding convention. This is a targeted UPX check, not a claim
that LibreOffice independently validates every MS-DOC invariant.

[Formatting algorithm](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417)
Part 1 step 7 applies unconditional table-style properties before step 9 consults
TTlp.grfatl for conditional differences. [Fatl](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/c2b2c89f-4ba1-4013-a459-b66caa1171c2)
defines fatlFont as information about the last auto-format, not a gate disabling
unconditional CFVanish. Therefore absence of a TTlp font switch does not justify
changing this phase's spec-derived expected visibility. The LO discrepancy remains.

Part 2 step 4 applies paragraph-style character modifications to that base;
[Applying Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/4e918665-c4da-41d8-aed5-615c2e96c216)
says the last applied modifier wins. Consequently no paragraph CFVanish operation
preserves the table base, while explicit paragraph CFVanish=0 replaces it. This
argument concerns absent versus explicit operations, not guesses about Word UI
style defaults. CPlain's definition explicitly requests the formatting algorithm
up to (but excluding) direct character formatting, so its reset base includes the
table contribution. Tests distinguish missing operations from explicit false.

## Row-context implementation

`_Props.applied_table_style` is nullable and separate from the normalized table
identity. It retains the effective explicit TIstd through inline, external PAPX,
and piece overrides. None never implicitly selects Normal Table (11).

`paragraphs()` now makes one structural CP scan before cleaning. It stores
budgeted paragraph metadata and pending lists per depth. A TTP assigns its
resolved Boolean visibility only to paragraphs at its own depth; nested lists
are independent. Each paragraph enters/leaves a pending list at most once.
Incomplete rows retain available text, warn, and mark note visibility unknown;
they never borrow a previous row or outer table's style. Context resets for each
existing story/note/textbox range. Paragraphs are cleaned once in original order,
without another output-text pass or per-character row lookup. The saved paragraph
properties are reused through the existing cache during cleaning/assembly.

Metadata and pending entries consume the existing aggregate record budget before
allocation; nesting uses max_depth. Context storage is O(paragraphs + depth),
not O(CPs). Table visibility is resolved once per complete row and included in
the character cache key. Paragraph style, character style, direct changes, resets,
and piece PRM use that underlying base. Note visibility sees the same effective
properties before text filtering. Structural cell/TTP marks remain intact.

## Validation

Independent review: **831 passed, 3 skipped** across DOC regressions, plus
31 independent checks of nested/incomplete rows, auxiliary story boundaries,
separate note bodies and external-PAPX acceptance/fallback. The live notes suite
passes **79 tests** after integration. Ruff passes.

Every explicitly forbidden UpxChpx property is rejected for paragraph,
character and table styles; legal CFVanish remains accepted. Conditional
operands remain opaque and warned. Public fixtures verify inherited hiding,
explicit show, unchanged cell geometry and text outside the table.

Context metadata is charged before allocation. References see effective
visibility before filtering; ordinary paragraphs are cleaned once. Incomplete
rows keep available text and unknown visibility rather than borrowing a style.
Conditional table formatting and other table-style properties remain unsupported.

## Bookmark ambiguity: explicitly unresolved

[Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
names a range-level protection bookmark but tests SDTI.sdtt=sdttPara.
[PRTI](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d6511a08-c896-4297-b208-f0ebfdb62352)
has no sdtt; [SDTI](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/05548762-7e8c-42bf-a75f-b36229c6493e)
belongs to structured-document-tag bookmarks.
[FibRgFcLcb2003](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/f6b7d624-570c-4057-acfd-cba71d12f1a0)
stores separate Prot/Sdt families. Do not join them by index or treat arbitrary
protection ranges as paragraph-type tags. This remains a genuine structural
question requiring clarification/interoperability evidence, not formatting-only.

