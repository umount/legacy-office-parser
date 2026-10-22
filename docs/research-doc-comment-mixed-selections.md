# DOC comment selections mixing ordinary text and complete outer rows

This extends the 0.24 whole-row proof with contiguous ordinary source paragraphs.
It publishes only the original bookmark endpoints; it never widens a selection,
copies selected text, reconstructs missing bookmarks, or derives source CPs from
an output grid. Comment bodies, reference anchors and flat text are unchanged.

## Primary basis and deliberately bounded scope

[MS-DOC Plcfbkf, rule 1](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff)
is the applicable table rule: annotation bookmarks have
[BKC.fCol=0](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b59cbd01-2391-4b70-994c-b58104d3f4c0).
For selected cell marks, a start before the cell and a limit outside the table
are allowed. For selected TTPs, starts outside the table or at a row start, and
limits outside the table or immediately after a TTP, are allowed. This supports
the narrow combination of ordinary text and complete rows without interpreting
partial-row or column-selection semantics. The bookmark specification replaces
the general valid-selection table rules; its rule 2 is not the annotation rule.

The other [valid-selection requirements](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8d8fece5-bdbc-4258-8457-916540075e3f)
remain. This implementation retains the stronger existing refusal of non-point
spans whenever field delimiters occur anywhere in the main story. It accepts no
new cross-section selections, partial rows, inner-row-only ranges, unknown
coverage, unsupported controls, or incomplete nested tables.

A table endpoint must be exactly a proven outer-row start or the exclusive end
of a proven outer TTP. An ordinary endpoint may be inside a safe ordinary
paragraph, including its ordinary CR, but may not split a UTF-16 surrogate pair.
Multiple complete tables separated by safe ordinary text may form one span.
Unequal source rows can be accepted even when output-grid padding creates
omitted positions: those output positions are not source cells.

## Implementation and bounds

`whole_row_comment_selections(..., include_ordinary=True)` reuses the existing
iterative row/nesting proof. Rows are published only after the entire candidate
table closes; a later incomplete row still invalidates its pending rows.
Safe depth-zero paragraphs and published complete rows become source atoms.
Gaps, unsafe paragraphs and section-ending paragraphs split their contiguous
runs. The four additional arrays store starts, ends, ordinary/row type and run
identity. Queries use two binary searches and two source-unit reads, without
rescanning paragraph records or allocating selected-text copies.

The default row-only helper keeps its previous behavior and charge. The mixed
index charges `10 * paragraph_count + 1` records before allocation/traversal,
instead of `6 * paragraph_count + 1`; the caller's existing ordinary-selection
index separately charges `4 * paragraph_count + 1`. Aggregate callbacks, explicit
record limits, source-character limits, depth and cell limits all remain active.
The supplemental index is constructed lazily once per invocation, only after an
ordinary proof fails and a potentially relevant outer row exists. Construction
is linear in source units/paragraphs; each mixed query is O(log paragraphs).

## Literal original transport and raw PLC regressions

`tests/test_doc_comment_mixed_selections.py` constructs original synthetic
FIB/CLX/PAPX/comment/bookmark streams. Its main story is exactly:

```text
Intro\rA\x07B\x07\x07Outro\x05\r
```

The two-cell outer row is `[6,11)`, reference CP is 16, and the ordinary main
story ends at CP 18. Independent FIB-pair/FBKF.ibkl reads verify source bookmark
endpoints, sentinel 19 and BKC zero before parsing. Literal accepted spans include
`[0,16)`, `[0,11)`, `[6,16)`, `[2,13)`, `[5,12)` and `[0,18)`. The original row-only
control `[6,11)` remains accepted. The body is `Body` and the reference anchor is
`['blocks', 2]`; neither changes with selection endpoints.

Negative cases keep null bounds for partial rows rather than widening them.
Other tests cover unsafe/unknown ordinary paragraphs, section boundaries, fields
outside the selected table, missing cell completion, invalid row definitions,
unknown cell coverage, malformed source marks, noncontiguous prepass records,
fully closed nested rows, two separate complete tables, split astral endpoints,
preallocation budget failure, aggregate exhaustion, and repeated queries after
removing the original paragraph records. The preexisting omitted-grid regression
now expects its exact `[0,20)` source range because both source rows are complete.

## Authored CFB and honest external-reader limit

`tests/fixtures/doc_comment_mixed/` contains an original FODT, its LibreOffice
7.4.7.2 DOC export, independent FODT readback, a fixture-only inspector, and saved
raw/XML evidence. The source annotation encloses ordinary text, a two-cell table,
and ordinary suffix text. The XML probe reports the literal logical selection
`Intro\rA\rB\rOutro 🚀`; its paragraph separators are an XML inspection convention,
not DOC cell/TTP CPs. The independent raw reader imports no runtime parser.

**LibreOffice drops this range during DOC export.** The original exported DOC
has annotation tag `0xffffffff`, empty bookmark parts 37/42/43, and reference CP
27. Its readback contains a point annotation, retaining the author and body but
no selection end marker. The parser correctly retains `[27,27)` and the body
`Review paragraph and table together.`. The saved regression asserts this loss;
it does not assert successful mixed-range roundtrip or infer missing endpoints.

Thus the accepted mixed subset is established by primary bookmark rules and
literal original transport tests. This authored external-reader probe demonstrates
conversion loss, not interoperability confirmation for stored mixed bookmarks.
A future independently authored DOC retaining those bookmarks would strengthen
the evidence without changing the refusal to invent absent ranges.

Reproduce with an isolated profile (test-only office process):

```sh
libreoffice -env:UserInstallation=file:///tmp/doc-mixed-profile --headless --convert-to 'doc:MS Word 97' --outdir tests/fixtures/doc_comment_mixed tests/fixtures/doc_comment_mixed/authored.fodt
libreoffice -env:UserInstallation=file:///tmp/doc-mixed-profile --headless --convert-to fodt --outdir tests/fixtures/doc_comment_mixed/readback tests/fixtures/doc_comment_mixed/authored.doc
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/fixtures/doc_comment_mixed/inspect_fixture.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_doc_comment_mixed_selections.py tests/test_doc_comment_complex_selections.py tests/test_doc_comment_selections.py tests/test_doc_comment_selections_review.py
```
