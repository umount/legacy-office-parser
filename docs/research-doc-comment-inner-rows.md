# DOC comments selecting one complete inner row

Base: `b55a3df` (0.26). This extension publishes an existing annotation bookmark
only when it selects exactly one complete depth-two row, wholly inside a proven
outer cell, with no deeper table inside that selected row. It changes selection
metadata, not extracted text, body ownership, reference anchors, or rendering.

## Primary proof and deliberate boundary

[MS-DOC Plcfbkf 2.8.10](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff)
uses its rule 1 for bookmarks whose BKC.fCol must be zero.
[BKC 2.9.8](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b59cbd01-2391-4b70-994c-b58104d3f4c0)
requires zero for annotation bookmarks. A row-start bookmark whose exclusive
limit is immediately after that row's TTP satisfies the applicable cell-mark
and TTP endpoint conditions. This is a sufficient subset, not a claim that all
other annotation selections are invalid.

[Overview of Tables 2.4.3](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
defines inner cell and TTP marks as U+000D with PFInnerTableCell/PFInnerTtp,
respectively. A row has 1–63 cells followed by its TTP; the row definitions must
match that source cell count. A nested table belongs to a cell at the preceding
depth. This establishes the ownership proof: the selected depth-two row contains
its own cell/TTP marks but none of its enclosing outer cell/row terminators.
It therefore does not require selecting the outer row as well.

The implementation does not apply the bookmark rule for other fCol types and
does not infer a column selection. It also does not generalize by equal depth:
multiple inner rows, rows from different parent cells, inner/outer mixed spans,
selected depth-three rows, and selected rows containing deeper tables remain
outside this extension. Existing supported complete outer rows remain supported,
including their already-proven fully closed nested contents.

## Reused proof and publication

`whole_row_comment_selections(..., include_inner=True)` uses the existing
iterative source-row stack, paragraph coverage, delimiter checks, cell counts
and strictly increasing row edges. At a valid depth-two TTP it records a pending
exact `(row_start, after_TTP)` pair only if that row contained no deeper table.
The deeper-content flag resets at each depth-two row end or when leaving that
nested table, so an earlier deep row does not poison a later plain inner row.

Pending pairs are published only when the entire enclosing outer table finishes
with a closed stack and no invalid structure. Unknown parent/inner/outer
coverage, an unclosed cell, invalid row definition, or a later malformed row in
the same enclosing table invalidates the pending proof. An explicit parent
depth is required; missing ancestor levels are never invented. A subsequent
separate invalid table does not erase a previously closed table's proof.

The integration remains lazy: an ordinary proof must fail, an enclosing outer
row must exist, and the candidate must end exactly after a depth-two inner TTP
(or meet a previously supported supplementary endpoint condition). The index
is built once per selection-validation invocation. `contains` checks the exact
CP pair; it never widens a start/end or combines adjacent inner rows.

Field delimiters anywhere in the main story keep the existing global refusal
of non-point selection proofs. Section marks inside the candidate table prevent
publication. This stage adds no mixed cross-section table support. Source CPs
remain unnormalized UTF-16 positions; hidden text does not shift them. A low
surrogate cannot start a newly proven row. Endpoints after the verified inner
TTP cannot split a surrogate pair. Unknown/missing bookmark metadata still cannot
be reconstructed from text or an output anchor.

## Bounds

The helper's default behavior and charges are unchanged. With `include_inner`,
it charges an additional `3 * paragraph_count` records before traversal or
allocation for pending and retained exact CP pairs. Thus row-only plus inner
costs `9*n+1`, and mixed/outer plus inner costs `13*n+1`. The caller's ordinary
selection index still separately charges `4*n+1`. Runtime enables the additional
charge only when the prepass contains a depth-two inner TTP; outer-only stories
keep their previous supplemental charge.

All charges use the existing explicit and aggregate budgets. Source-character,
depth and cell limits remain in the shared traversal. At most one candidate is
stored per row; no Cartesian product of possible row endpoints is built. Work
and storage remain linear in source/paragraph count, with constant expected-time
exact-pair queries and no per-comment source rescans or selected-text copies.

## Original literal transport evidence

`tests/test_doc_comment_inner_rows.py` uses original synthetic FIB/CLX/PAPX,
annotation and bookmark streams. The positive source is literally:

```text
P\rA\rB\x05\r\rQ\x07\x07
```

Properties distinguish these otherwise identical CRs: `P` is an outer-cell
paragraph, `A` and `B` end depth-two cells, the next empty CR is their inner TTP,
`Q` ends the outer cell, and the final U+0007 is its outer TTP. The independently
authored expected inner range is `[2,8)`, selecting `A\rB\x05\r\r`.
Direct raw FIB/FBKF reads verify start 2, `ibkl=0`, limit 8, BKC zero and bookmark
sentinel 12, independently of the runtime proof. The main reference CP remains
5 and its anchor remains
`['blocks',0,'rows',0,0,'blocks',1,'rows',0,1]`. Body `Body` appears once; its
body-block range stays `[0,1)`. Serialization and normalization retain metadata.

Literal negative neighbors `[3,8)`, `[2,7)`, `[2,6)`, `[4,8)`, `[0,8)` and
`[2,10)` stay unproven. The old complete outer-row control `[0,11)` still works.
Further positives/negatives cover two individually selectable inner rows whose
union remains unsupported, equal-depth rows in different outer cells, deeper
selected contents, a plain row after deeper contents, astral CPs, hidden source
text, malformed/unknown ancestor and row structure, fields outside the range,
section barriers, late incomplete enclosing rows, and precharge/aggregate limits.

This evidence is primary-specification reasoning plus original literal binary
transport tests, not a claim of successful Word/LibreOffice roundtrip. Earlier
research demonstrated converter range loss; no conversion is used to generate
expected CPs or to justify missing bookmark recovery here. No private corpus,
formula/macro execution, or layout inference is involved.

Validation:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_doc_comment_inner_rows.py tests/test_doc_comment_complex_selections.py tests/test_doc_comment_mixed_selections.py tests/test_doc_comment_selections_review.py
.venv/bin/ruff check src/legacy_office_parser/doc.py src/legacy_office_parser/_doc_comments.py tests/test_doc_comment_inner_rows.py
```
