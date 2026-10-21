# Narrow static inline PPT footer substitution

Implemented 2026-10-21. Owned changes: `ppt.py`,
`tests/test_ppt_inline_fields.py`, and this document. No model changes,
comment extraction, computed fields, external reads or Office automation in the
runtime parser. Existing fixtures and test expectations are unchanged.

## Primary contract

[MS-PPT FooterMCAtom, 2.9.49](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5a2fa1e2-bc5f-450b-89d0-b372a811313a)
specifies a metacharacter replaced by the corresponding stored footer. The
corresponding text is associated with the closest preceding TextHeaderAtom.
Its header requires version/instance zero and a four-byte position payload.
[TextPosition](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/7f3c80c2-01d9-4cb9-97f2-adb082b01a35)
provides the text position; implementation uses original UTF-16 code units.

[PerSlideHeadersFootersContainer](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/0104cfcf-3781-4fbb-954d-5cd43e2d4e35),
[HeadersFootersAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/5ba5b716-138d-4643-9dbd-fa1382d25082),
and [FooterAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/be368875-33e9-490d-b832-954eb800a240)
provide the slide-local settings, enabled-footer bit and stored UTF-16 string.
The new path deliberately requires this local container and an explicit footer
string. It does not infer missing strings from document defaults or masters.

[RTFDateTimeMCAtom, 2.9.52](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/7aa3736d-15cf-43b3-8b45-0dddf856d946)
is type 4117, version/instance zero, payload length 132: four-byte position plus
128 bytes describing a datetime format. It requires datetime formatting, not a
stored field result. We validate the record envelope and associated position and
warn; the format bytes are not interpreted, executed, or emitted as content.

## Supported subset

The slide's immediate child records are collected once so the local settings
are known before outline and shape text are read, regardless of record order.
Settings use the existing validated header/footer parser. Only enabled local
footer settings with an explicit FooterAtom activate substitution.

Each TextHeaderAtom starts an independent association. A supported association
has exactly one TextCharsAtom or TextBytesAtom, one or more distinct FooterMC
positions, and no other metadata records. Positions may occur before or after
the text atom and need not be sorted. The target character must be the ordinary
single-unit `*` marker. That is an intentional narrow support gate, not a claim
that arbitrary metacharacter encodings are invalid. UTF-16 surrogate pairs are
never split or replaced.

Raw text is decoded before normalization. Position lookup counts supplementary
characters as two UTF-16 units; leading whitespace, CR/LF, nulls and other
normalizable characters retain their original offsets. Replacement uses the raw
stored footer, followed by the existing normalization once on the expanded text.
This preserves spaces required between the footer and neighboring native text.

Example authored input: `Owner: *`, FooterMC position 7, enabled slide-local
footer `Finance Team`. Previous output: `Owner: *` with warnings. New output:
`Owner: Finance Team`, without a warning for this supported association.

Successful replacement marks the footer as already emitted, preventing the
later supplemental footer path from appending another copy. Ordinary body text
with the same value is retained. Separate text headers/shapes and repeated marker
positions in different associations remain distinct content. No value-based
cross-shape deduplication is introduced. State is reset for each slide/notes
object and cleared before inherited master text is read.

## Fallbacks and malformed input

Disabled or missing local settings, document-default-only settings, missing
FooterAtom, mixed field kinds, unknown metadata, multiple text atoms in one
association, non-asterisk targets and surrogate-interior targets retain stored
text with the field-not-evaluated warning. A valid explicit empty FooterAtom
replaces the marker with an empty string. Unknown/mixed status applies to the
individual TextHeader association, not unrelated text elsewhere on the slide.

Duplicate positions, including different field kinds at the same position,
fail closed. Out-of-range positions, orphan field records, wrong MC
version/instance and incorrect payload sizes also fail closed. Positions are
validated against the unnormalized text length on association flush. Existing
DateTimeMC format-index validation remains. RTF datetime markers now join this
validated path and warn instead of being silently ignored.

Ordinary styles and formatting metadata are conservatively outside the new
inline subset. Such records may later be admitted individually with a proven
association contract; no generic extension/metadata allowlist is introduced.
No inherited-footer substitution, notes/footer synthesis, date generation,
slide numbering, RTF format evaluation or layout/visibility inference is added.
The supported local inline path does not require master placeholder placement:
the explicit marker already supplies a location in the slide's native text.

## Resource accounting

Source text is charged by the existing decoder before allocation. Every inserted
footer copy is additionally charged in UTF-16 units. The entire repeated-footer
charge is checked before decoding the footer or building the expanded output.
We deliberately do not refund replaced marker units: this is bounded parsing
work as well as output accounting. Repeated slides pay again. The final document
text and separators retain their existing independent output check.

The existing record count bounds the marker map and child-descriptor list;
existing depth and stream limits remain. Expansion checks use Python integer
arithmetic without multiplication-sized string allocation. No limits increased.

## Authored evidence and validation

`tests/test_ppt_inline_fields.py` contains 54 independent synthetic cases with
literal expected results. The `complete_cfb` helper constructs an original CFB
v3 entirely in memory: FAT, directory and the two PPT streams. The real
`parse_ppt_bytes` / olefile path reads it without mocking the OLE layer and
produces `Owner: Finance Team`. It contains only authored structural records and
text; no private or third-party file content is embedded.

This is a complete CFB reader-path check, **not** an Office-rendering oracle.
No LibreOffice or PowerPoint rendering confirmation is claimed. No persisted
fixture was modified or created; the generator lives in the new test file.

Tests cover UTF-16 supplementary characters, raw whitespace/newline offsets,
unordered/adjacent markers, multiple headers, marker-before-text association,
compressed text, empty footers, duplicate/overlapping markers, mixed and unknown
metadata, unsupported settings, state reset, ordinary matching body text,
RTF datetime validation, repeated-slide budgets and the real OLE reader path.
An instrumented decoder proves a two-copy expansion over budget fails before
footer decoding. The exact accepted boundary is tested too.

Validation:

```sh
.venv/bin/python -m pytest -q tests/test_ppt*.py
.venv/bin/ruff check src/legacy_office_parser/ppt.py tests/test_ppt_inline_fields.py
```

**306 passed** (252 existing plus 54 new); Ruff clean.

## Same-shape geometry equivalence

Inline expansion retains the normalized original text as comparison-only source
evidence alongside the rendered block. Geometry is compared with both versions
only for the exact shape containing the native text or its validated outline
reference. Outline source strings stay aligned with individual outline blocks;
references do not acquire equivalence to any other block. These original strings
are never emitted as additional content. Source decoding remains charged once,
and the additional references/storage remain bounded by the already charged
source text and record counts. State is cleared before master traversal.

Thirteen regressions cover native and outline associations, both record
orders, matching original geometry, matching expanded geometry, distinct artwork,
equal text on another shape, and nonmatching referenced-outline-block controls.
`Owner: *` plus FooterMC position 7 and identical same-shape geometry now emits
only `Owner: Finance Team`; unrelated geometry with `Owner: *` still survives.
