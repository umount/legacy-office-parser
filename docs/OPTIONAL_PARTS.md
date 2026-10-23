# Missing optional parts

Missing optional metadata or an empty auxiliary story must not block available
content. Recovery emits a diagnostic where needed, preserves limits and never
invents source text or relationships. This is not a blanket exception handler:
required structure, invalid references, encryption and budget failures still fail.

DOC zero-length headers tolerate bounded zero-CP tables; absent notes/comments
tolerate zero-entry body tables with no reference entries. Present unrelated
metadata is still validated. See [DOC](DOC.md) and the [error contract](OUTPUT_FORMAT.md#failures-and-exception-boundaries).

Regression modules cover optional parts in each format:
`test_doc_absent_optional_stories.py`, `test_doc_header_ranges.py`,
`test_xls_optional_metadata.py`, `test_ppt_optional_audit.py`,
`test_rtf_optional_parts.py`, `test_odf_optional_parts_audit.py`.
