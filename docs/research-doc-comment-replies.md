# DOC comment reply relationships

This extension exposes validated `AtrdExtra` parent relationships without
reordering comments or recursively projecting their bodies. It preserves source
ordinals, including gaps caused by omitted bodies. The original comment ownership
and source-selection rules remain in force.

## Primary specification

- [MS-DOC 2.9.5, AtrdExtra](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/1b6a50f8-de0c-4020-bce0-06e24660c928)
  defines an array parallel to the reference records, with the same number of
  entries, in preorder. Parentage means that one comment comments on another.
- [MS-DOC 2.9.6, ATRDPost10](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/19181fe7-a62a-4e70-9a5f-a0cb1ebe0921)
  gives the 18-byte record: four-byte date, two ignored padding bytes,
  four-byte unsigned depth, four-byte signed parent displacement, and four flag
  bytes. Depth and displacement start at offsets 6 and 10. Displacement is in
  units of 18 bytes relative to the current record. Roots have depth and
  displacement zero; a child has its parent's depth plus one. The ink flag
  does not authorize rendering or evaluating content.
- [MS-DOC 2.8.7, PlcfandRef](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/9d82ca25-ff21-488c-bee2-dd654935c65a)
  locates references in the main document. Reference positions must be distinct,
  carry U+0005, and have CFSpec set. The parallel index binds the extra metadata
  to an existing reference, not to newly discovered text.
- [MS-DOC 2.9.7, ATRDPre10](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/f2327847-8ba3-4b9c-b9a3-b0bdfac1206c)
  independently binds a reference to its author and selection bookmark; a
  sentinel bookmark tag represents a point selection.

These sections do not specify that a reply must share its parent's main-text
selection. They do not establish every constraint imposed by Word's authoring
UI or every document-wide conformance requirement. Accordingly, the fixture
below is an **authored metadata probe**, not a claimed Word-created reply document
or a proof of full Word conformance. Its separate paragraph/cell anchors are
preserved from the original fixture. No relationship is inferred from anchors,
authors, repeated body text, dates, or LibreOffice output.

## Public model and JSON

Two optional fields are appended to `Comment`:

- `reply_depth: int | None = None`
- `parent_ordinal: int | None = None`

Absent metadata leaves both fields `None` and both keys omitted from JSON. A
validated root emits `reply_depth: 0` and `parent_ordinal: null`. A validated
child emits a positive depth and the original ordinal of its retained parent.
The fields are source relationship metadata, never body offsets or CPs.

If a parent body is omitted, both relationship fields are cleared on its retained
child. The same policy propagates to descendants whose ancestry is no longer
known. Their bodies, authors, ordinals, selections, and reference anchors remain
available. A warning identifies unavailable ancestry. This intentionally does
not expose even the known source depth of an orphan: the small public model
requires a complete retained chain to a proven root. Independent roots and
siblings whose actual ancestry remains known are unaffected. Missing metadata
never creates a root.

API validation rejects negative, boolean, or noninteger depths; parent values
without depth; positive depths without parents; root parents; dangling, forward,
self, or wrong-depth parents; and reopening an ancestor already closed by a
known preorder transition. Unknown entries cannot prove a branch closure, so
validation preserves the last known ancestry across them. An unknown entry
cannot itself serve as a parent. Original ordinal gaps remain valid.

## Bounded implementation

The existing decoder validates every present extra record, even when ownership
PLCs are absent. It checks array size/count, the depth limit, and the exact
preorder ancestor at the declared parent displacement before returning source
metadata. The signed displacement cannot wrap into an unsigned index. Padding
and reserved bits retain their specification-mandated ignored behavior.

The source extra-record count is charged before building the metadata array or
ancestor stack. Source descriptors remain bounded by the existing record charge.
During body publication, each retained comment is charged before inserting its
ordinal/depth in the retained-parent map. This map allows constant-time parent
availability checks; no descendant scan or recursive traversal is needed.

The API prechecks the combined note/comment metadata count, then charges each
comment before inserting its known ancestry. Its stack has at most
`max_depth + 1` entries. Each stack entry is appended and removed at most once.
Decoder and publication work are linear in comment count; the API relationship
check is also linear. Existing source-text, author/initials, body, anchor-path,
stream, and total record budgets continue to apply. No additional body is copied
or projected for a parent link.

## Original CFB probe and independent readback

`tests/fixtures/doc_comment_replies/fixture.py` deterministically copies the
repository's original `doc_comments/authored.doc` and changes only the
same-sized `AtrdExtra` depth/displacement/flag fields in its Table stream. It
preserves dates, all other streams, body text, and main-text selections. It uses
`olefile` for CFB transport and imports no production parser.

The three authored records are, in original ordinal order:

1. Depth 0, relative parent 0: a root.
2. Depth 1, relative parent -1: parent ordinal 1.
3. Depth 2, relative parent -1: parent ordinal 2.

The same helper reads those fields directly from the FIB-selected Table-stream
slice. `evidence.json` records both the original probe and saved independent
readback. Regeneration is byte-for-byte deterministic. The source text provenance
is the original `doc_comments/authored.fodt`; that XML describes the text, not
the subsequently authored binary reply relationships.

Literal reference CPs remain 20, 38, and 61. Selection ranges remain [10,20),
[38,38), and [51,61). The projected comment text is exactly:

```text
Shared comment.
Shared comment.
Cell comment: Ελληνικά.
Second paragraph.
```

The Greek text is literal multilingual fixture evidence. Equal first and second
bodies remain two distinct bodies; the final paragraph appears once. Neither
parent links nor tree depth add recursive text copies.

LibreOffice **7.4.7.2** imported the authored DOC and exported another DOC.
The raw readback records are three roots, with every depth and displacement
zero. All three textual bodies survive unchanged. This is observed loss of
relationship metadata for this probe, **not positive independent evidence of
reply support or full fixture conformance**. The parser reports the readback's
roots as stored; it does not reconstruct the lost relationships.

To regenerate the probe and run the independent live check:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/fixtures/doc_comment_replies/fixture.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/pytest -q -p no:cacheprovider tests/test_doc_comment_replies.py -k live
```

The live test uses an isolated LibreOffice profile and temporary output directory.
Conversion is a test oracle only; runtime extraction executes no office program,
macros, commands, network fetches, or reply rendering.

## Regression coverage and limits

Tests distinguish absent metadata, explicit roots, siblings, independent roots,
nested replies, omitted ancestors and descendant propagation, ordinal gaps,
malformed displacements and depths, closed preorder branches, ink warnings,
record/depth limits, and public JSON omissions. The real CFB probe and independent
raw inspection verify literal relationships and unchanged body projection.
Public API/autodetect/CLI tests exercise the same original fixture.

Ink rendering, timestamps, resolved state, inferred relationships, and replies
without proven retained ancestry remain outside this extension. Nothing changes
which source selections are considered valid or which comment bodies are owned.

Validation for this implementation: 1,203 DOC/model/passive-security tests passed,
with six opt-in tests skipped. The focused reply/API/review run passed 50 tests
with one live test skipped; that live LibreOffice test was then run separately
and passed. All 15 independent reply-review cases pass, including the two closed
branch regressions. Ruff passes for the changed Python files. A separate runtime
regression verifies that an omitted child and unknown retained grandchild do not
prevent a later proven sibling from linking to the retained root.
