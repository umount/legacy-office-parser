# DOC comment selections across ordinary paragraphs

Research and implementation: 2026-10-22. This extends source selection bounds
without changing comment bodies, author metadata, reference anchors, the public
model, or text projection. Runtime parsing is passive: it executes no macros,
field instructions, external commands, or resource fetches.

## Evidence and supported scope

The earlier implementation published non-point selections only within one
paragraph. An original DOC now demonstrates two ranges preserved by LibreOffice
but previously emitted with null selection bounds:

- `[8,22)`: `Alpha\r\rBeta 🚀`, including an empty middle paragraph.
- `[50,61)`: `Gamma\rDelta`, after an unrelated table.

Both are UTF-16 source CP intervals. The first follows an emoji and also includes
an emoji, so neither its start nor its length can be derived from Python string
indices. Main reference CPs remain 22 and 61. Their final output anchors remain
`['blocks', 2]` and `['blocks', 5]`, respectively: these identify reference
containers, not every paragraph intersected by the selected range.

The extension supports ordinary cross-paragraph ranges with proven paragraph
coverage, and multiple paragraphs within one source cell whose closing marker
is proven. It does not infer table boundaries from matching depth, style,
direction, or normalized output coordinates. Entering and leaving a nested table
breaks the selection proof, even if the outer depths match.

## Primary specification basis

[MS-DOC 2.2.3 Valid Selection](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8d8fece5-bdbc-4258-8457-916540075e3f)
requires endpoints in one document part and whole-field inclusion when a field
delimiter is selected. It does not forbid crossing paragraph marks. Its ordinary
table-row rule is specialized for bookmarks by the bookmark specification.

[MS-DOC Plcfbkf](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff)
permits overlapping bookmark CPs, requires ordered range endpoints, and adds
specific table constraints. A range containing a cell mark or TTP requires
additional start/limit relationships to cells and rows. This implementation does
not attempt that extension: selected table terminators are excluded from the
supported subset. A multi-paragraph range wholly inside one cell contains no
cell/TTP boundary and needs no guessed grid or row equivalence.

[BKC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b59cbd01-2391-4b70-994c-b58104d3f4c0)
requires annotation bookmarks to have `fCol=0`. The existing decoder continues
to reject nonzero annotation fCol, resolve the reference tag through ATNBE, and
follow FBKF.ibkl to the exclusive end. It never pairs endpoints by sorting them.
The annotation record and ownership details are documented in
[DOC comments](research-doc-comments.md).

## Bounded source-region proof

The existing structural paragraph prepass still establishes table context
before text cleaning. Selection validation builds three indexes and one bounded
set: paragraph starts, cumulative unsafe-paragraph counts, source-region IDs,
and completed-cell region IDs. It charges `4 * paragraph_count + 1` records
before allocating or traversing these structures.

A paragraph is ordinary only with known table context and PAPX coverage. Its
content must contain ordinary text, tabs, or annotation marks; unsupported
controls make that paragraph unsafe. The current conservative field policy is
unchanged: any field delimiters in the main story prevent publication of
non-point spans, even if a particular span appears outside the field.

Source regions continue across ordinary CR paragraph endings at unchanged
depth. They break on an explicit cell/row terminator, section boundary,
non-CR ending, or depth change. This permits consecutive ordinary paragraphs
outside tables without inspecting page layout. It also distinguishes paragraphs
inside the same source cell from equal-depth paragraphs in different cells.

For a multi-paragraph table span, a region additionally needs a proven closing
cell mark: an outer U+0007 cell mark distinct from the row terminator, or an
inner CR with the inner-cell property distinct from the inner TTP. The closing
marker needs known paragraph context even if it lies beyond the selection's
end. An incomplete cell cannot become proven merely because a later TTP supplies
row formatting. Existing same-paragraph behavior remains unchanged.

For each range, binary searches locate the first and last intersected paragraphs
using `begin` and `end-1`. Prefix counts establish that all intersected paragraphs
are safe; region equality establishes that no unsupported structural boundary
was crossed. This does not rescan each selected paragraph for every comment.

Ordinary CR may be included, including an empty paragraph's CR. An exclusive
end at the next paragraph's start still belongs to the preceding selected CR.
Cell, TTP, and section terminators cannot be included. Endpoints splitting a
UTF-16 surrogate pair are not published. Hidden/deleted text is not removed from
source-coordinate calculations, so filtering cannot shift selection CPs.

Malformed PLC bounds, reversed ranges, bad tags/indexes, and metadata budgets
retain the existing decoder policy. A structurally unsupported selection keeps
its body, author, and proven reference anchor, but has null bounds and a warning.
Missing range metadata is not repaired. Point comments retain their existing
zero-length bounds. Reply-tree and ink behavior are unchanged.

Index construction is O(source CPs + paragraphs), with O(paragraphs) additional
storage. Each selection costs O(log paragraphs), including heavily overlapping
ranges. Existing depth, cell, record, source-text, and retained-text limits still
apply before output publication. No selected source text is copied into the
comment model, and bodies are still projected exactly once.

## Original CFB and independent LibreOffice evidence

`tests/fixtures/doc_comment_selections/` contains:

- `authored.fodt`: original literal XML with two comment ranges, an empty
  paragraph, two emoji, and an intervening table outside both ranges.
- `authored.doc`: real CFB export using LibreOffice 7.4.7.2, filter `MS Word 97`.
- `readback/authored.fodt`: independent DOC import/export with LibreOffice.
- `inspect_fixture.py`: fixture-only XML annotation-range inspection plus the
  earlier independent CFB/FIB/CLX/CHPX reader. It imports no runtime parser.
- `evidence.json`: saved raw records and source/readback findings.

The XML probe joins annotation starts and ends by name across host paragraphs,
skipping annotation bodies while accumulating selected text. It retains literal
CRs between paragraphs. The raw reader resolves bookmark tags and ibkl separately
and slices raw UTF-16 with the resulting CPs. Neither uses the new runtime
selection checker to construct expected values.

Observed stored values:

- Main story length: 69 CP; comment story length: 55 CP.
- Reference CPs: 22 and 61; reference sentinel: 70.
- Body boundaries: 0, 25, 54; ignored final slot: 55.
- Tags: 0 and 1; bookmark starts: 8 and 50; limits: 22 and 61.
- Authors: Ada Range and Ben Range; initials are empty.
- Each main/body reference marker has direct CHPX `55 08 01` (CFSpec=true).
- Bodies: `Across empty paragraph.` and `Across ordinary paragraphs.`.

Source XML, raw DOC selections, and LibreOffice readback agree exactly on the two
literal selected strings above. Runtime body block ranges remain `[0,1)` and
`[1,2)`, and the comment projection remains
`Across empty paragraph.\nAcross ordinary paragraphs.`. The saved test also
checks literal CPs; the live test checks each generated binary against its own
raw records and XML readback.

The XML probe is intentionally specific to this original fixture; it is not a
general ODF parser or whitespace oracle. The authored source is byte-stable,
while converter metadata can change when regenerating DOC/readback files. No
whole-office-suite parity is inferred. Multi-paragraph same-cell behavior is
covered by independent synthetic DOC records, not claimed as a LibreOffice
conversion result of this fixture.

## Reproduction and regression coverage

From the repository root:

```sh
libreoffice -env:UserInstallation=file:///tmp/doc-comment-selection-profile --headless --convert-to 'doc:MS Word 97' --outdir tests/fixtures/doc_comment_selections tests/fixtures/doc_comment_selections/authored.fodt
libreoffice -env:UserInstallation=file:///tmp/doc-comment-selection-profile --headless --convert-to fodt --outdir tests/fixtures/doc_comment_selections/readback tests/fixtures/doc_comment_selections/authored.doc
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/fixtures/doc_comment_selections/inspect_fixture.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_doc_comment_selections.py tests/test_doc_comments.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/pytest -q -p no:cacheprovider tests/test_doc_comment_selections.py -k 'live or real_cfb'
```

Independent regressions cover two/three paragraphs, an empty middle paragraph,
endpoints before/on/after CR, final ordinary CR, astral endpoints, split-surrogate
refusal, hidden source text, unknown middle coverage, fields, section crossings,
multiple paragraphs within an outer/inner cell, different cells, a selected
inner-cell CR, nested-table crossings, incomplete cells, missing closing-marker
coverage, omitted grid positions, overlaps, permuted ibkl, malformed bounds, and
depth exhaustion.

A non-timing test validates 256 overlapping long ranges while counting accesses
to the paragraph sequence. The total stays linear in paragraph and range counts;
paragraph slices are forbidden. A separate budget test fails before any
paragraph access or index allocation when the prefix-index charge exceeds the
record limit. The earlier test expecting null for `First\rSecond` now expects its
literal `[0,12)` range, supported by the independent cross-paragraph fixture.

## Remaining limits

Selections crossing cells, rows, nested tables, section boundaries, unknown
paragraph coverage, or unsupported controls retain null bounds with warnings.
This includes otherwise valid whole-row/table bookmark ranges: their additional
selection rules have not been implemented. No normalized output-range mapping,
page layout, revision acceptance, field evaluation, or reply-tree model is added.
