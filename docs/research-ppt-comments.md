# PPT presentation comments: authored fixture proof

Research and approved implementation, 2026-10-21. The original complete CFB
fixture demonstrates active presentation comments retained by LibreOffice.
The initial research proved an extraction gap; the implementation below now
preserves those comments separately from body and notes.

## Files and provenance

- `tests/fixtures/ppt_comments/comments.ppt`: original two-slide presentation,
  461,312 bytes. SHA-256:
  `ca7b6d62b69dbd467116445113cbc966a1680b2ef7d282ccb840e48b35209aed`.
- `tests/fixtures/ppt_comments/generate.py`: UNO authoring and read-only verification
  script, using the MS PowerPoint 97 export filter and an isolated profile/pipe.
- `tests/fixtures/ppt_comments/uno-readback.json`: separate body/comment readback.
- `tests/test_ppt_comments_research.py`: research proof, active-record inspection,
  current-gap assertion, and an opt-in fresh LibreOffice read-only check.

Only authored text was used. The fixture was exported through LibreOffice 7.4;
no binary payload was patched after export. It contains no authored macros,
formulas, external links or executable actions. The generator resolves the actual
UNO `MacroExecMode.NEVER_EXECUTE` constant (0), disables document updates and
uses read-only loading for verification. It asserts that reading does not change
the input bytes. Source creation and readback require no runtime parser changes.

Slide 1 body: `Slide body 1`. Its two comments are:

- Research Author / RA: `Budget excludes migration`.
- Review Author / RA: `Привет — проверить` followed by a newline and
  `Second comment line`.

Slide 2 body: `Slide body 2`. It also has a separate comment by Research Author /
RA containing `Slide body 2`. This intentionally establishes that identical
comment/body values must not be deduplicated across source kinds.

The source requested initials RV for Review Author. The exported record and
independent reader both contain RA. The fixture expectations preserve the actual
stored value and do not claim exact preservation of that authoring property.
An attempt to set a fixed annotation timestamp stalled inside LibreOffice's UNO
setter. Those isolated processes were stopped and the final generator omits the
setter. Exported comment settings contain zero datetime components; timestamp
semantics are outside this text proof. No created/modified date is inferred.

## Primary contracts

[MS-PPT 2.5.24 PP10SlideBinaryTagExtension](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/ccb82f60-e1ae-4379-b1e0-00909bb70b17)
defines the `___PPT10` tag and its array of presentation comments. The bounded
path is the active slide's ProgTags container, ProgBinaryTag, exact CString tag
name and BinaryTagDataBlob. Do not search arbitrary strings or stale records.

[2.5.25 Comment10Container](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/1a15453d-859f-48ee-8dcd-4d51ab9227f8)
is type 12000, version 15, instance 0. It contains optional author, text and
initials records plus the required Comment10Atom. These are presentation comments,
not body text or speaker notes.

[2.5.27 Comment10TextAtom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/509e23de-6838-4693-b586-dace9899c2c8)
is CString type 4026, version 0, instance 1, even byte length no greater than
64,000. Its payload is comment text permitting tabs and line breaks.
[2.5.26 author](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/e6a12f24-3819-41ca-a4c6-df5065ca75ec)
and [2.5.28 initials](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/e4516e96-f95c-4358-9e69-c7e58ef19061)
use CString instances 0 and 2 respectively, version 0, even lengths up to
104 bytes. Missing optional records must remain missing, not inferred from peers.

[2.5.29 Comment10Atom](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/75f27659-7c4b-4bf3-ad31-d5e221c24494)
is type 12001, version/instance 0, 28-byte payload. It supplies a nonnegative
signed comment index, stored datetime structure and anchor. Anchors are display
metadata, not evidence that the comment is ordinary slide artwork.

LibreOffice's primary [XAnnotationAccess API](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1office_1_1XAnnotationAccess.html)
provides creation and enumeration of annotations. Its
[XAnnotation API](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1office_1_1XAnnotation.html)
separates Author, Initials and TextRange from the slide's shapes. These independent
interfaces supplied the fixture authoring and readback evidence.

## What was verified

The research test resolves the latest persist graph and active slide list using
existing parser primitives, then independently inspects the exact comment
container path and wire payloads. It checks record versions, instances, sizes,
unique string roles, a required settings atom, and nonnegative index. This is a
fixture-specific research reader, not a new general production parser or a proof
of every malformed-input case. Sharing active-object resolution is disclosed;
comment text expectations are literal, not generated by the extraction parser.

Both the immediate post-export read-only reopen and a **fresh isolated
LibreOffice process** returned the same three comment records and separate body
shape lists. The fresh run was:

```sh
timeout 45 /usr/bin/python3 tests/fixtures/ppt_comments/generate.py \
  /tmp/ppt-comments-independent --read /tmp/ppt-comments-research/comments.ppt
```

Its readback matched the persisted JSON. Sandbox startup was unavailable, so
these isolated LibreOffice operations used authorized escalation. This is an
independent application import/readback check, not a visual rendering claim.

Before implementation, `parse_ppt_bytes` returned only `Slide body 1` and `Slide body 2`, empty
titles/notes, and the existing extension-content omission warning. That established the original gap. The research regression now asserts the
approved structured-comment result while keeping body and notes unchanged.

Validation completed before this checkpoint:

```sh
.venv/bin/python -m pytest -q tests/test_ppt_comments_research.py
.venv/bin/ruff check tests/test_ppt_comments_research.py tests/fixtures/ppt_comments/generate.py
```

**3 passed, 1 skipped; Ruff clean.** The skipped test is the environment-gated
fresh LibreOffice pytest oracle. The equivalent fresh-process script was run
successfully as described above; do not report the skipped pytest as executed.

## Approved implementation contract

Public `SlideComment(text: str, author: str = '', initials: str = '')` is exported
from the package. `Slide.comments` is appended as a fresh default-empty list,
preserving existing positional constructor arguments. Empty comments lists are
omitted from JSON. Nonempty lists serialize text, author and initials per item.

Comments preserve source order and owning slide. Slide body, title and speaker
notes are unchanged. `Document.text` appends each nonempty comment's text after
that slide's own notes, before the next slide. Author and initials stay in the
structured data and are not injected into plain text. The slide-2 comment equal
to body text remains a separate record and a separate projection occurrence.
ODS drawing and structured note fields and serialization are unchanged.

The parser reads only direct Comment10 containers under the exact typed
`___PPT10` envelope of an active ordinary slide. It does not scan arbitrary
CStrings, unknown nested extension records, inactive persists, masters, notes,
or reviewer diff trees for comments. Unknown sibling extensions retain the
existing omission warning; the existing bounded metadata classifier is reused
for known timing-only siblings. Successfully recovered comments alone no longer
produce the generic omission warning.

Comment container headers, optional string roles/lengths/UTF-16, duplicate
strings, required 28-byte settings, settings header, and nonnegative signed index
are validated. Duplicate settings and overlapping duplicate PPT10 envelopes with
comments fail closed. Metadata-only duplicate envelopes keep the previous warning
fallback. Unexpected comment child metadata warns and is not interpreted. C0 controls and U+007F–U+009F are rejected before normalization, except
tab/CR/LF in comment text. Authors and initials permit none of these controls. Existing text
normalization handles surrounding whitespace and line endings.

The index is validated but not exposed by the approved model. Stored timestamps
and anchors are not decoded into values, calculated or used for layout. Missing
optional strings become empty strings. Empty comments may still retain author
metadata and remain structured records even if absent from the plain projection.

All strings, including author and initials, pass through the shared preallocation
UTF-16 budget. Container traversal consumes shared record/depth budgets. Final
PPT projection accounting includes comment text and separators before document
return. API defence-in-depth checks comment types, all stored strings, cumulative
comment count, and projected slide separators without constructing Document.text.
No budgets increased. No field or command execution, network access, dates or
layout behavior was added.

## Validation

Tests cover source order, owning slides, notes projection, optional fields,
Unicode, stale content, duplicate body/comment values, malformed settings and
strings, source-size boundaries, record/depth/output budgets and JSON compatibility.
All C0 and DEL/C1 code points are checked in every role; only comment text accepts
tab, CR and LF. The authored presentation has independent LibreOffice UNO readback.

The focused PPT suite passed 562 tests with one optional reference test skipped.
Independent review found no remaining actionable issues after corrections.
