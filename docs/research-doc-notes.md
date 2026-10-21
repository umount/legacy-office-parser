# DOC note bodies and source anchors

Research/implementation: 2026-10-21. Runtime is passive: no office process,
macros, field evaluation, links, or resource fetching. LibreOffice is used only
by the authored fixture generator and opt-in tests. No numbering/layout engine
or inferred custom reference labels are introduced.

## Primary sources

- [MS-DOC 2.8.19 PlcffndRef](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/3ed81d85-ea74-4790-8579-ab7f8eb651f7)
- [MS-DOC 2.8.20 PlcffndTxt](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b30472e7-569e-4c9c-a8ca-07fd5432f365)
- [MS-DOC 2.8.16 PlcfendRef](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/50371008-8334-4d3f-80c2-9bcd6dbe1c93)
- [MS-DOC 2.8.17 PlcfendTxt](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/49650ca7-1bfc-49e5-93ac-01a86bd2fc3e)
- [MS-DOC 2.5.6 FibRgFcLcb97](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/0c9df81f-98d0-454e-ad84-b612cd05b1a4)
- [MS-DOC 2.2.1 Character Position](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/a3d44e16-7d29-46f7-bb7b-d0d8a5734f83)
- [Character properties: CFSpec, visibility, CSymbol](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/7022285b-9621-42e9-ad4d-4e02c115ef18)

Ref PLCs have N references, N+1 CPs, and N two-byte indicators: length 6N+4.
The last CP is ignored. Used CPs are unique, ordered, and inside main text.
Zero indicator means custom; any nonzero value means automatic. It is not a
body index, OOXML ID, or displayed note number. Automatic references require
U+0002 and CFSpec=true.

Text PLCs have N+2 CPs. The first N+1 delimit N bodies; the final CP is ignored.
Used boundaries are unique, ordered, and inside the corresponding note story.
The penultimate CP equals story length minus one. Each body ends with CR.
Footnote ranges are relative to the footnote story after main text; endnote
ranges are relative to the endnote story after main/footnotes/headers/comments.

The decoder pairs references and bodies by ordinal only when their counts
agree. Authored conversion plus independent raw PLC inspection corroborates
this pairing. Reference flags are deliberately NOT used as indexes. The
experiment does not prove that an exporter preserves arbitrary source-document
relationships: the counterexample below demonstrates why those claims differ.

## Additive public model

`Document.notes` defaults to an empty list and is omitted from JSON when empty.
`Note` has `kind` (footnote/endnote), a positive 1-based `ordinal`, nullable
`source_cp`, `reference_kind` (automatic/custom/unknown), nullable `anchor_path`,
`visibility`, and `body: NoteBodyRange`.

`NoteBodyRange(story, block_start, block_end)` is a half-open range in
`Document.story_blocks[story]`, where story is footnotes or endnotes. Plain
paragraphs are retained there when notes are modeled. Notes do not duplicate
text or block trees. Legacy footnotes/endnotes strings remain projections;
`Document.text` includes each story once, not once again per note record.
The reserved final story CP is parsed after the discrete bodies and retained
outside every note's block range. This preserves the legacy trailing empty
paragraph and its newline in the story projection and `Document.text`.

An anchor path uses JSON-shaped structural steps, for example:
`["blocks", 2, "rows", 0, 1, "blocks", 0, "rows", 0, 0]`.
It ends at an actual Paragraph or Cell, never a Table or omitted coordinate.
Simple cells retain their existing projected text; an anchor targets that cell
rather than inventing a retained paragraph. Covered source cells are not moved
to the merge origin. Frame/table splitting and grid normalization finish before
paths are resolved by object identity.

`source_cp` is a source coordinate, never an index into normalized text. The
fixture's first reference is CP 14 but Python string index 13 because an emoji
precedes it. Removed fields, reference marks, hidden/deleted characters and
symbol conversion create further differences. No normalized character offset
is exposed.

Visibility is a list of flags: hidden, deleted, field_hidden,
field_instruction, unknown. Empty means no suppression detected with available
CHPX/style coverage; unknown is the default for unresolved/unlinked metadata.
The flags are not an accepted/rejected revision view. Hidden/deleted references
retain their structural relationship; body text independently follows existing
visibility filtering. CFFldVanish is distinct from being inside field
instructions. Unknown CFSpec leaves an automatic reference unanchored rather
than guessing. Custom labels and automatic numbering are not reconstructed.

## Algorithm, failure policy, and bounds

The decoder reads FIB pairs 2/3 and 46/47. All sizes, source lengths, used CP
bounds, required CR terminators and record budgets are checked before emitting
relationships. Both PLC arrays, including their sentinel slots, are charged to
the aggregate record budget before lists are constructed. The sentinel values
are not used as ranges. A malformed present PLC raises InvalidDocumentError;
limits always raise LimitExceededError.

Missing text PLC: preserve the whole legacy story and warn, without note records.
Valid body ranges but missing/count-mismatched references: retain every body,
with source_cp=None, reference_kind=unknown, anchor_path=None and unknown
visibility. Never zip only the surviving/visible references. A valid nonzero
initial text boundary leaves unassigned text; preserve the whole story and warn
rather than silently drop the prefix. References with no bodies emit no invented
body. No heuristic search repairs missing relationships.

The main scan observes reference CPs before normalizing/filtering text. Stable
paragraph/cell identities survive cell projection. Each note body gets its own
table assembler and field-state finish, preventing adjacent note tables or
malformed fields from swallowing the next note. Only then are body block ranges
and output paths published. Public API validation checks enum values, ordinals,
nonoverlapping body ranges, source CP bounds, paths, metadata budgets and the
retained story trees. Body references are not charged as additional text copies.

The source scan remains linear in CP count; PLC decoding is linear in entries.
Anchor lookup is dictionary-based; path resolution traverses the final tree
using lazy child iterators and one mutable path. Traversal storage is O(depth),
in addition to the O(notes) target map and budgeted published paths; siblings
do not allocate path copies. All notes matching one container are charged to
the aggregate record budget before any corresponding path is copied/published.
Path length is bounded by existing table depth. Existing record, cell, source
text and retained text budgets still apply. The parser never follows source
paths to external resources.

## Independent authored evidence (LibreOffice 7.4.7.2)

`tools/generate_doc_notes_fixture.py` writes XML/ZIP with fixed timestamps using
the standard library, importing no parser code. Arbitrary note IDs, duplicate
bodies, a custom marker, an astral character, references in outer and nested
cells, hidden/deleted references, and a note containing a table are authored.

The positive fixture has six footnotes and two endnotes. Independent CLX/PLC
reading in the tests gives:

- Main/footnote/endnote story lengths: 117 / 132 / 35 CP.
- Footnote references: 14, 36, 48, 60, 99, 115; indicators 1, 0, 2, 3, 4, 5.
- Footnote text CPs: 0, 15, 31, 46, 80, 105, 131, 132.
- Endnote references: 73, 84; indicators 1, 2.
- Endnote text CPs: 0, 17, 34, 35.
- Ref sentinels are 285, outside main text, and are correctly ignored.

DOCX references are resolved by ID independently of the production code. Raw
DOC body order and the positive round-trip relationships agree. Hidden/deleted
states survive this conversion. A separate negative fixture preserves the
counterexample with reversed endnote ID/reference order: its DOC export and
round-trip swap the original endnote relationships. Reordering XML elements
alone did not fix this observed exporter behavior; the positive fixture uses
consistent ID/reference order. The parser represents what is stored in DOC,
not the lost source DOCX mapping.

Additional observed conversion losses are retained as explicit evidence:

- The source custom body `* Custom body.` becomes `** Custom body.`. Neither
  parser nor oracle strips a guessed marker to hide the difference.
- The authored note table becomes an empty stored SHAPE field; NoteTableCell is
  absent from the binary note text and round-trip DOCX. This fixture therefore
  does NOT prove note-table fidelity. Independently authored synthetic binary
  table records test note-body table boundaries instead.

The files in `tests/fixtures/doc_notes/` are entirely authored, no private input:
`authored.docx`, `authored.doc`, `roundtrip.docx`, `unordered.docx`,
`unordered.doc`, `unordered-roundtrip.docx`. Rebuilding DOC changes producer
metadata; deterministic source reproducibility is tested byte-for-byte.

## Validation commands

```sh
.venv/bin/python -m pytest tests/test_doc_notes.py -q
OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/python -m pytest tests/test_doc_notes.py -q
.venv/bin/python tools/generate_doc_notes_fixture.py --convert
```

Synthetic tests cover malformed/truncated PLCs, ignored sentinel values,
count mismatch, absent PLCs, prefix gaps, aggregate budgets, unknown CFSpec,
field instructions, hidden/deleted references, reserved final CP, separate note
tables, normalized omitted coordinates, frame-driven table splits, and public
model validation. Full layout, label reconstruction, revision acceptance,
comments and anchors to other stories remain outside this contract.

### Validation

Notes tests: **78 passed, 1 skipped** normally; **79 passed** with live
LibreOffice conversion. Independent review verified PLC decoding, reference
association, visibility flags and body ranges; Ruff passes.

The authored fixture compares footnotes, endnotes and Document.text against
legacy whole-story extraction. The reserved final block remains outside all note
ranges. A 31-level, 40,030-cell tree verifies less than 1 MiB peak resolver
allocation, both with sufficient metadata budget and on bounded failure.
Aggregate path charging happens before publishing shared-container references.

Zero-body tests cover absent, empty and dangling reference PLCs. Leading
automatic/custom body markers and astral characters retain their literal bytes.
A range splitting a surrogate pair cannot satisfy the final-CR requirement;
that check is not a general UTF-16 validator. Printed labels are not inferred.

### Live conversion oracle correction (2026-10-21)

Newer LibreOffice CI reported footnote 4's range as [3, 7), versus [3, 6) in
the saved 7.4 fixture, with source CP 60 and its nested-cell anchor unchanged.
Comparing complete Note records across producer versions incorrectly made the
saved block layout a live oracle. The newer binary was not available locally;
the extra block's contents have not been guessed. Inspection of the saved binary
and XML shows ` Note table.`, an empty paragraph from a stored SHAPE field, and
`NoteTail` in its fourth body.

The live test now reads the generated DOC's CLX and raw reference/text PLCs
independently, without the production note decoder. It checks exact counts,
ordinals/source CPs, automatic/custom references and contiguous nonempty body
ranges. A separate OOXML oracle resolves roundtrip references by ID, derives
their structural container paths, and compares complete body signatures with
the generated model. Empty paragraphs, tables, cells, content, visibility and
the reserved final block remain checked. A fixture-specific passive field-result
projection checks raw body content against the associated XML. Source DOCX
reference contexts and custom/hidden/deleted flags must also survive conversion.

Persisted-fixture literal assertions remain unchanged. Added regressions accept
different valid block counts only when their own binary/XML evidence agrees;
wrong CPs, anchors, ranges, missing notes, changed content and extra structural
blocks fail. The saved binary also passes this oracle independently.

Actual validation: **93 passed, 1 skipped** normally; **94 passed** with local
LibreOffice 7.4 conversion; Ruff passed. The newer CI converter must still be
rerun. No blanket structural exception or missing-note allowance was introduced.

### Confirmed newer-export representation (CI 049e488)

Subsequent CI supplied the exact fourth-footnote body:
`\x02 Note table.\rNoteTableCell\x07\x07\rNoteTail\r`.
The model preserves a paragraph, a 1x1 table, an empty paragraph, and `NoteTail`.
Roundtrip DOCX instead contains a floating plaintext textbox in a host paragraph:
Choice uses drawing/anchor/graphic/graphicData/wsp/txbx/txbxContent, and Fallback
uses pict/rect/textbox/txbxContent. Both contained `NoteTableCell`. The old oracle
incorrectly concatenated both alternatives into the host paragraph.

The XML fixture consumer now selects the first understood WPS Choice, otherwise
one Fallback, and records textbox blocks separately from direct paragraph text.
Only for footnote 4 of this authored fixture, a mismatching representation may
pass after all these independent checks: exact raw body and cell/row terminators;
the original source's exact 1x1 table, single-column grid and surrounding text;
the exact four-block model with no covered/omitted/merged cells; and the same
note's exact three-paragraph XML host structure containing exactly one selected
textbox with one paragraph `NoteTableCell`. Other bodies still require exact
structural equality. No parser Table is flattened, and no arbitrary table/textbox
equivalence is inferred.

Regressions reconstructed from the supplied raw bytes and XML ancestor paths
reject wrong model cells/grid, flattened tables, wrong source CP, wrong drawing
text, missing/duplicate boxes, extra host text, boxes in another note, altered raw
row markers and an altered authored grid. An unselected differing fallback does
not contribute text. The saved LO 7.4 lost-table case and literal tests remain
unchanged. This establishes the specific export transformation, not full table
parity with LibreOffice.

Actual validation after this correction: **106 passed, 1 skipped** normally;
**107 passed** with local LO 7.4 live conversion; Ruff passed. The newer CI case
is covered by the evidence-based synthetic regression; the real newer CI rerun also passed in run 39673338931 (commit 8a949ba).
