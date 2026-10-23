# Missing optional parts and empty metadata

## Extraction policy

Absence of an optional part is not a reason to reject available document content.
Explicitly empty structures must be distinguished from truncated records and
references that require missing source text. Recovery never creates source
identities or relationships without evidence. Where a supported omission reduces
certainty, the document carries a diagnostic. All source and output budgets
continue to apply before recovery.

This is not a blanket catch of parsing exceptions. Required main-stream framing,
invalid ranges, ambiguous ownership, encryption and exhausted limits retain their
existing behavior. A successful parse does not promise complete rendering or
that every format feature is implemented.

## DOC corrections in 0.27.1

A declared zero-length header story can coexist with a degenerate PlcfHdd. After
stream-size/alignment and record-budget checks, all defined CPs must be zero;
the final undefined CP is ignored. The redundant table then contributes no
header text or identities and produces `doc_empty_header_plc_ignored`. The slot
count is irrelevant to a story with no contents. Nonzero defined CPs still fail.

Footnote/endnote and comment body tables can similarly contain a zero-entry
placeholder: one zero boundary and one undefined terminal CP. Recovery requires
an empty story and no reference entries. It emits `doc_empty_note_plc_ignored`
or `doc_empty_comment_plc_ignored`. Multiple claimed bodies, nonzero defined
boundaries and truncation do not qualify. Comment author/bookmark/reply metadata
continues to be validated; empty-body recovery does not bypass it.

Both helpers charge source records before recovery. Tests cover local and
aggregate exhaustion, undefined-sentinel values, missing/zero-entry reference
arrays, public main-text preservation and refusal of nonempty or malformed data.
The tests are original synthetic streams; no private document is distributed.

The DOC review also inspected FIB/table slicing, section/formatting absence,
style defaults, symbol fonts, textbox stories and note/comment ownership paths.
Existing absent formatting/font/textbox metadata fallbacks remain in force.
Dangling required style/font references are not reclassified as absent optional
metadata. This review does not establish acceptance of every valid DOC variant.

## Other format checks

The [XLS audit](research-xls-optional-metadata-audit.md) covers absent/empty print
headers and footers, shared strings, merge/dimension records, phonetic extensions
and blank formula caches. Forty-four regression cases found no new runtime fix.

The [PPT audit](research-ppt-optional-audit.md) covers optional slide/notes lists,
comment strings, footer/date values, Unicode usernames, extension arrays and
empty geometry metadata. Forty-eight cases found no new runtime fix.

The [RTF audit](research-rtf-optional-parts.md) covers metadata/header tables,
auxiliary stories, empty notes, absent field results, encoding/style defaults
and skipped destinations. Seventy-seven cases found no new runtime fix.

The [ODF audit](research-odf-optional-parts-audit.md) covers optional package parts,
styles and their scopes, empty master stories/notes and empty main collections
for ODT/ODS/ODP. Forty-five cases found no new runtime fix. Missing required
content/body structures and malformed present XML retain their existing errors.

These are reviewed, bounded code paths with regression evidence, not a proof of
universal input acceptance. Future refusal reports should be reproduced with an
original minimal fixture and classified under the same policy.
