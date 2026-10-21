# Nested RTF tables — implementation and evidence

Date: 2026-10-21. Scope: `rtf.py`, `tests/test_rtf_nested.py` and original
fixtures under `tests/fixtures/rtf_nested/`. Shared model/API are maintained by
the coordinating agent. This note supersedes the nested-table flattening boundary
in the older RTF research note; ordinary table and story policies remain applicable.

## Specification inspected before implementation

Microsoft's RTF specification, reproduced in the
[Document Area / Paragraph Text and Table Definitions](https://latex2rtf.sourceforge.net/rtfspec_7.html)
sections, was read before writing the implementation. In particular:

- `itap` is a scoped paragraph nesting property: main document zero, outer table
  one, nested table two and further levels thereafter. `pard` resets paragraph
  properties; writers commonly repeat `pard/intbl/itap2` between nested cells.
- `nestcell` and `nestrow` terminate nested cells and rows. `nesttableprops` is
  a recognized destination, including its starred form; its row properties must
  be interpreted instead of skipped as unknown optional data.
- Row properties may precede or follow content and may be repeated. Nested
  properties are normally emitted after their cells. The specification's nested
  example repeats the **outer** `trowd` after the nested properties even while
  the preceding paragraph still has `itap2`.
- `nonesttables` contains fallback for readers lacking nested-table support;
  supporting readers ignore it, avoiding duplicate visible content.

Only format facts were used. No external parser implementation or example text
was copied. Both checked-in documents are original fixtures, not downloaded files.

## Representation and parsing decisions

Each story owns a chain of table sinks, one per active level. Resolving a depth
and closing descendants are iterative. Group restoration changes paragraph depth,
not ownership of already accumulated rows. Each level owns its definitions,
merge state, cell fragments and table rows. This prevents late child properties
from overwriting parent geometry. Late outer properties work through `intbl`.

A complex `Cell` stores its ordered content in `blocks`: before paragraphs,
nested tables, and after paragraphs. Its `text` is a single projection of these
blocks: newlines between blocks/rows and tabs between cells. Descendants appear
once in visible `Document.text`; rendering does not concatenate `text` and
`blocks` a second time. Simple cells keep empty `blocks`, omitted by the shared
`to_dict()` implementation. Actual paragraph boundaries are tracked independently
from soft `line` characters, including a trailing soft newline.

Adjacent nested rows at the same level stay in one table. Returning to a parent
paragraph closes that table; a subsequent nested table becomes another block.
Separate outer cells and separate stories cannot share nested tables. Header,
footer, note and textbox tables retain the existing story-string projection.

Ordinary merges within a nested table use the existing merge rules. Rows whose
cells contain nested tables conservatively retain their coordinates and warn
when marked for merging, avoiding destruction of a child's blocks.

## Malformed data and budgets

Invalid/missing/negative nesting parameters, skipped parent levels, orphan nested
terminators, and properties attempting to change depth or close an outer row/cell
raise `InvalidDocumentError` (a `ParseError`). `itap0` within an unfinished outer
row warns and preserves its parent cell. Incomplete nested rows, missing cell
terminators/properties, mismatched cell counts and conflicting repeated row
properties recover with `Document.warnings`; all text and coordinates survive.
Conflicts use the final properties and report that choice. Unknown/skipped
ancestor destinations cannot reopen table processing.

A malformed outer `cell` terminating an active child recovers the child as a
nested table, with warnings. It does not silently revert the declared hierarchy
to flat text. The new test explicitly specifies this behavior.

All physical nested cells, including empty and recovery-padded cells, count toward
`max_cells`. Cell definitions retain their separate cumulative budget, including
repeated definitions, as in the existing parser. Every retained ancestor text
projection is charged **before allocation**, in addition to original text and
nested descendants; all projection separators are included. The accounting is
conservative because consumed paragraph separators remain charged. For documents
with nested tables, the size of the public `Document.text` projection, including
body/story separators, is checked without allocating it. The preexisting flat
RTF budget behavior remains compatible. Both brace depth and table depth are
limited independently; resource exhaustion raises `LimitExceededError`.

The 1100-level synthetic test raises the caller's depth limit deliberately and
checks iterative recovery and cell counting, without calling recursive dataclass
serialization. The default depth limit remains 32.

## Original fixtures and independent checks

`own_nested.rtf` was authored here with an outer two-cell row, before/after body
paragraphs, before/after paragraphs in the first cell, and a nested two-by-two
matrix. Tests specify literal expected cells and marker ordering independently;
they never generate expected values from this parser.

LibreOffice **7.4.7.2 40(Build:2)** converted this fixture to FODT. XML assertions
verified two tables, the child table physically inside the first outer cell,
two nested rows with two cells each, and all nine markers in order without the
fallback text. A separate profile, headless mode, `SAL_USE_VCLPLUGIN=svp` and a
45-second subprocess timeout isolate this optional development oracle. The initial
sandbox launch failed before conversion; the authorized external process launch
succeeded. LibreOffice is not a runtime dependency.

`own_nested_lo.rtf` is LibreOffice's RTF export of that generated FODT, checked in
as a real-writer fixture. Its nested hierarchy and every marker are preserved.
This LO version emits an extra outer `cell` immediately before `row`; the parser
retains that empty coordinate and warns about the count mismatch. Unsupported
font metadata/optional destination warnings are unrelated to nested tables.

Reproduce the import oracle:

```sh
RTF_NESTED_LO=1 .venv/bin/python -m pytest tests/test_rtf_nested.py -q
```

Reproduce the writer fixture by converting `own_nested.rtf` to FODT with an
isolated LO profile, naming a copy `own_nested_lo.fodt`, then converting that copy
back using `--headless --convert-to rtf`. The writer fixture was not hand-edited.

Synthetic coverage additionally includes multiple child tables, separate outer
cells, three levels, empty intermediate parents, Unicode/fields, skipped fallback,
soft breaks, nested merges, late/repeated/conflicting properties, malformed depth,
story isolation, retained projection budgets and structural limits.

## Validation and integration

The recovery regression in `test_rtf_fidelity.py` checks nested structure,
unchanged visible text and an explicit warning for missing row properties.
`test_malformed_outer_terminator_keeps_recovered_child_instead_of_flattening`
checks that a recovered child is retained instead of flattened.

Final targeted verification: all 149 tests across `test_rtf.py`,
`test_rtf_fidelity.py` and `test_rtf_nested.py` pass with both LibreOffice oracles
enabled. Ruff passes for the implementation and affected test files.
