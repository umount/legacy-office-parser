# RTF optional-part refusal audit

## Result and scope

No proven refusal caused solely by absent optional parts or empty auxiliary
metadata was found in the audited RTF runtime at committed baseline
`84b34520967bd6523f9cb85fa8c726367d2c7778`. No runtime change is proposed.
This is a bounded audit of the areas below, not a universal validity claim.
The isolated copy was extracted from `git archive 84b3452`; uncommitted DOC
changes were not copied. Only this note and a dedicated synthetic test module
are added. No diagnostic code is needed.

## Primary contracts

Microsoft's [RTF 1.5 specification, reproduced by Biblioscape](https://www.biblioscape.com/rtf15_spec.htm)
is a primary Microsoft-authored format document hosted by a third party.
Its RTF Syntax/Reader Conventions permit unused groups to be absent and require
unrecognized starred destinations to be skipped. The Information Group grammar
makes its members optional, including date/time components. Headers/Footers
defines absent-section-header inheritance, which is distinct from extraction's
pooled-story output. Fields requires both instruction and result destinations,
even when no result has been calculated; accepting a missing result group is
therefore tolerance, not normative optionality.
The audit does not infer that every present table may have zero entries:
font/file/style table grammars impose their own structure. Empty-table acceptance
below is recorded as existing tolerance, not as proof that malformed tables are
valid. Code Page Support does not establish that a missing parameter or zero
codepage is a valid optional value; no such relaxation is made.

Microsoft's [MS-OXRTFEX 2.1.3.3, Encoding Plain Text into RTF](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/1e44fa4c-3ea3-402c-8b21-fb19a617e43b)
explicitly allows a font table to be emitted, recommends a default code page,
and permits other nontext formatting controls. It does not make a font table
mandatory for every plain-text RTF document. This corroborates testing absence
without treating a missing table as corrupt body structure.

## Audited paths and observed behavior

- Lexer/root validation (`_tokens`, `parse_rtf_bytes`, `_Parser.parse`): optional
  semantic content does not bypass balanced braces, lexical escape validation,
  exact binary lengths, root/trailing-data rules, or file/stream limits.
- Header metadata and `_SKIP` destinations (`destination`, `word`): absent
  font/color/style/list/revision metadata is not required for ordinary text.
  Empty info, empty string metadata, zero word/character/edit-time counts, and
  absent timestamp members preserve body text without inventing metadata.
- Font/encoding handling: missing table/charset/codepage data uses existing
  defaults; unknown positive codepages retain the established warned fallback.
  Present invalid codepages are not excused as missing optional metadata.
- Stylesheet observer/resolution: empty stylesheet input is tolerated; missing
  base styles retain available properties and the existing warning. No style
  fallback is promoted to source evidence or a fabricated heading.
- Auxiliary sinks/finalization: all eight header/footer destinations accept empty
  content and explicit empty paragraphs without failing or manufacturing text.
  Footnote/endnote separator destinations remain omitted. Empty notes retain an
  empty paragraph and exact one-block body range, with no fabricated source CP
  or anchor. This is existing note-boundary behavior, not new rendering support.
- Fields: absent/empty cached results emit no result text (absence of the
  result group is tolerated, not spec-valid); populated results are
  retained. Instructions are not emitted or evaluated.
- Unknown optional destinations: nested story/field-like controls cannot reopen
  skipped content, modify body encoding, or activate nested-table interpretation.
- Pictures, objects, annotations and zero-entry table groups: empty groups do not
  refuse the whole document. Existing omission diagnostics remain. This records
  tolerant handling and does not establish full format conformance or extraction
  of these unsupported objects.
- WordArt property text/legacy drawing paths were read for optional missing-data
  failures: unsupported/incomplete property candidates are omitted, while accepted
  text overflow remains a limit error. No new drawing semantics are proposed.

## Regression evidence and boundaries

`tests/test_rtf_optional_parts.py` adds original byte-string tests separating
normatively optional absence/metadata from deliberately labelled empty-destination
tolerance. It checks unchanged body blocks, empty auxiliary projections, exact
empty-note ranges, no invented anchors, existing diagnostic codes, Unicode
fallback defaults, and absent style-base behavior.

Adversarial tests require failure for unclosed groups, truncated/negative binary
lengths, invalid hex escapes, trailing junk, invalid present body controls, and
depth/record/file/stream/text exhaustion. Skipped binary bytes containing braces
are consumed by their declared length. Empty auxiliary groups do not reset the
text budget. Exact depth/text thresholds pass at the bound and fail below it.

No `ParseError` catch, parser suppression, limit reset, output fabrication,
private fixture, converter, or runtime dependency was added. General RTF rendering,
header inheritance reconstruction, field evaluation, and unsupported destination
extraction are outside this refusal audit.

## Validation

- New audit module: **77 synthetic cases**, all passed in the RTF run.
- `python -m pytest -q tests/test_rtf*.py`: **834 passed, 33 skipped**.
- Ruff on the new module: **passed**.
- `rtf.py` is byte-identical to the committed `84b3452` baseline.

Skipped checks are not claimed as executed. Only the dedicated tests and this
research note are proposed for integration; no runtime delta is necessary for
the audited optional/absent/empty cases.
