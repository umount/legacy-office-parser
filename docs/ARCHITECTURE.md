# Architecture

The library extracts faithful text and structure for LLMs. It is synchronous and
has one runtime dependency, `olefile`. It does not execute macros, formulas or
scripts, follow links, or render pages. The caller owns process/time/memory limits.

## Modules

- `api.py`: bounded input, format detection and parser dispatch.
- `doc.py`, `xls.py`, `ppt.py`, `rtf.py`, `odf.py`: format readers and their private helpers.
- `_ole.py`, `_odf_package.py`: container checks and bounded stream access.
- `models.py`, `limits.py`, `errors.py`: public structures and refusal contract.
- `_validation.py`: output structure, source relationships and aggregate limits.
- `normalization.py`: optional copy-based display cleanup.
- `cli.py`: text/JSON interface to the same API.

DOC/RTF/ODT produce ordered paragraphs/tables and separate auxiliary stories.
XLS/ODS produce sparse sheets; raw values and display strings stay separate.
PPT/ODP produce ordered slides with titles, text, notes and supported metadata.
The [output contract](OUTPUT_FORMAT.md) defines fields, coordinates and omissions;
[integration](INTEGRATION.md) describes consumer policies.

## Development rules

Read source structures rather than guessing tables or scanning arbitrary text.
Preserve active document ownership, source positions and raw numeric values.
Missing optional parts should not block available content; recovery must not
invent relationships. Apply budgets before allocations and during traversal.

Keep changes focused: one implementation and its necessary regression tests.
Test rules separately from transport/traversal so independent dimensions do not
create redundant Cartesian products. Run changed tests locally; full suites and
reference checks run in CI after push. See [testing](TESTING.md).
