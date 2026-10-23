# DOC comment selections across ordinary main-story sections

This narrow extension accepts source bookmark spans crossing validated section
marks in ordinary, non-table main-story paragraphs. It preserves the original
UTF-16 CP endpoints, reference anchor, author, body ownership and text projection.
It adds no model fields, layout interpretation or selected-text copies.

## Primary evidence and choice of scope

[MS-DOC Valid Selection, 2.2.3](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8d8fece5-bdbc-4258-8457-916540075e3f)
requires both endpoints to be in the same document part. It places extra
same-owner restrictions on notes, headers, comments and textboxes, but does not
require a main-story selection to remain within one section.
[Plcfbkf, 2.8.10](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff)
applies those non-table selection constraints to bookmark ranges and resolves
the exclusive limit through FBKF.ibkl. This stage does not expand its special
table rules.

[PlcfSed, 2.8.26](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/68a959a6-11e0-4f3e-9a99-76ca8cc4dddc)
defines sections as ranges within the main document. An interior section start
has a preceding U+000C; a U+000C not ending a section is a manual page break.
The terminal PLC CP is not another section start and can extend beyond the main
story. [Determining Paragraph Boundaries, 2.4.2](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/30461a5b-e3ad-44cd-a3fe-038f86639b13)
allows an end-of-section character to terminate a paragraph.

Together these rules establish a sufficient proof for ordinary main-story
paragraphs crossing an explicitly identified section mark. They do not justify
calling every form feed a section, guessing a paragraph's table membership, or
recovering endpoints from visible text. Inner-row-only selections remain outside
this stage; their nested ownership rules are not inferred from matching depth.

## Implementation and refusal boundaries

The existing `_Doc._sections` validator proves PLC structure/order/main-story
coverage and verifies the U+000C preceding every interior section CP. The
existing paragraph scanner uses that set to distinguish section terminators
from inline page breaks.

`_comment_selection_ranges` now uses one shared ordinary-ending predicate for
region continuity and the last included delimiter. In addition to ordinary CR,
it permits U+000C only at a validated section endpoint and only when paragraph
table depth and membership are both zero and row/inner-cell/inner-TTP flags are
absent. Existing known-context and PAPX-coverage checks, unsafe-paragraph prefix
counts and surrogate endpoint checks still apply.

This allows a bookmark to start on or include a verified section mark, end just
after it, or cross several ordinary sections including empty paragraphs. Hidden
source text remains part of the source CP calculation. It does not authorize
cross-section spans containing tables; the supplemental mixed-row index is
unchanged and still treats section paragraphs as barriers. A U+000C without
interior PLCSED evidence remains an unsupported control for this selection proof.
Malformed section metadata raises rather than falling back to guessed bounds.

Fields anywhere in the main story still disable non-point selection proofs.
Unknown paragraph coverage, unsupported controls, source table transitions and
surrogate-splitting endpoints retain null bounds and the existing diagnostic.
Unproven or absent bookmark metadata is never repaired. Comment bodies/reference
anchors remain available under their existing contracts.

The ordinary index charge remains `4 * paragraph_count + 1`, before traversal
and allocation, using the existing aggregate budget. No new retained index or
source buffer is added. Construction is linear in source units and paragraphs;
each selection uses binary search and constant-time prefix/region checks.
Overlapping ranges do not rescan selected paragraphs. Stream, source-character,
retained-text and metadata limits are unchanged.

## Literal synthetic transport regressions

`tests/test_doc_comment_section_selections.py` builds original FIB/CLX/PAPX,
PLCSED and annotation-bookmark streams. For `A\fB\x05\r`, the literal section
CPs are `[0,2,5]`, the reference CP is 3, and the anchor is `['blocks',1]`.
Direct FIB-pair reads and FBKF.ibkl resolution verify bookmark endpoints before
runtime parsing. Accepted examples include `[0,3)`, `[0,2)` and `[1,2)`; no endpoint
is widened or converted into a normalized display offset. Body `Body` is emitted
once.

The astral/multiple-section case is `😀A\f\rB🚀\fC\x05\r`, with section CPs
`[0,4,9,12]` and reference CP 10. It checks literal endpoints around both
surrogate pairs and both section marks. Additional regressions cover missing and
malformed PLC evidence, unknown boundary/following paragraphs, fields outside the
selection, cross-section table spans, exact preallocation limits and 256 heavily
overlapping ranges. Existing section-refusal tests are updated only for the now
proven ordinary cases; manual page-break and table refusals remain.

## Original DOC and independent raw/readback evidence

`tests/fixtures/doc_comment_sections/` contains original FODT, its LibreOffice
7.4.7.2 DOC export, FODT readback, saved evidence and a fixture-only inspector.
The source uses a two-column section to force a real stored section boundary;
column layout is not interpreted by this feature. A trailing ordinary paragraph
keeps the final exported section nonempty.

The independent reader imports no runtime parser. It reads raw CLX text,
annotation tag/FBKF.ibkl endpoints and PLCSED CPs, and checks the source units
at each interior section boundary. Literal observations:

- Main/comment stories: 44/24 UTF-16 units.
- Section CPs: `[0,14,29,69]`; 69 is the terminal sentinel, not a new section.
- Annotation tag 0, source reference CP 21, bookmark `[8,21)`.
- Raw selected source: `Alpha\fBeta 🚀`.
- Author `Ada Section`, body `Review both sections.`; output anchor `['blocks',1]`.

Version 0.25 retains the body and anchor but returns null selection bounds with
the unproven-selection warning. The new proof returns exactly `[8,21)` with no
warning on this original DOC. Source XML expresses the same selected paragraph
content with an XML-probe paragraph separator (`Alpha\rBeta 🚀`); that is not a
claim that XML paragraph separators are DOC CP delimiters.

**LibreOffice readback drops the annotation end**, although the exported DOC's
raw bookmark retains the range. The saved regression asserts that loss instead
of treating the point annotation in readback as a range oracle. This differs
from the earlier mixed-table fixture, whose export already lacked a bookmark.
The positive evidence here is the primary specification plus literal original
DOC/PLC and synthetic transport records; universal office-reader parity is not
claimed.

Reproduction (isolated test-only profile):

```sh
libreoffice -env:UserInstallation=file:///tmp/doc-section-profile --headless --convert-to 'doc:MS Word 97' --outdir tests/fixtures/doc_comment_sections tests/fixtures/doc_comment_sections/authored.fodt
libreoffice -env:UserInstallation=file:///tmp/doc-section-profile --headless --convert-to fodt --outdir tests/fixtures/doc_comment_sections/readback tests/fixtures/doc_comment_sections/authored.doc
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/fixtures/doc_comment_sections/inspect_fixture.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_doc_comment_section_selections.py tests/test_doc_comment_selections.py tests/test_doc_comment_selections_review.py tests/test_doc_comment_mixed_selections.py tests/test_doc_sections.py
```
