# ODS ordinary floating text

Research and approved follow-up implementation, 2026-10-21.
Scope: a separate narrow implementation for ordinary text boxes and
rectangle/ellipse/custom-shape text directly inside a sheet's `table:shapes`.
This evidence is positive, unlike the earlier inline embedded Writer probes.

## Primary specification and independently read fixture

[ODF 1.3 Part 3 §9.2.8](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html)
defines `table:shapes` as the shapes anchored on its containing table. Its permitted
children include frames, rectangles, ellipses and custom shapes. Sections 10.4.3,
10.3.2, 10.3.9 and 10.6.1 specify the respective text containers. The
[official ODF 1.3 RNG](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/schemas/OpenDocument-v1.3-schema.rng)
accepts the authored content.xml. Ordinary shapes' `draw-text` consists of p/list;
a text box permits the broader text-content grammar. Frame alternatives still
require one supported representation, not concatenation of every child.

`tests/test_ods_floating_research.py` creates `floating.ods`, entirely from authored
XML, with sheets North and South. Each sheet has one real A1 string cell and four
sheet-anchored drawings in XML order: text-box frame, rect, ellipse, custom-shape.
No external/archive references, inline office objects, scripts, or images occur.
The ZIP contains mimetype, content.xml, and a matching manifest. Schema validation
of content.xml passes; schema validation alone is not a blanket conformance claim.

LibreOffice 7.4.7.2 Calc independently exposes all eight objects through each
owning sheet's DrawPage. Its exact strings are:

* North: `North text-box paragraph\nNorth text-box list`,
  `North rect paragraph\nNorth rect list`,
  `North ellipse paragraph\nNorth ellipse list`,
  `North custom-shape paragraph\nNorth custom-shape list`.
* South: the same four strings with `South` replacing `North`.
* Real cells remain North.A1 = `North cell` and South.A1 = `South cell`.

The reader asserts the entire JSON object: owning sheet name, actual A1 value,
drawing name, and exact drawing string, in order. This is model-level evidence,
not a claim to reproduce Calc's layout. It uses isolated profile/UNO IPC,
read-only hidden loads, NEVER_EXECUTE macros, and NO_UPDATE document updates.

Reproduce from the staging repository root:

```sh
PYTHONPATH=src:tests .venv/bin/python tests/test_ods_floating_research.py /tmp/ods-floating-research
ODF13_SCHEMA=/tmp/odf-inline-evidence/schema.rng ODS_FLOATING_LO=1 .venv/bin/python -m pytest -q tests/test_ods_floating_research.py
/usr/bin/python3 /tmp/ods-floating-research/reader.py /tmp/ods-floating-research
```

All 3 tests passed with schema and Calc oracle enabled; Ruff passed. Tests assert
positive independent-reader behavior, never permanently assert parser omission.
For later CI, install LibreOffice and system Python UNO, permit local IPC, and
provide the development schema path. These are optional development tools only.

## Previous omission and extraction paths

The parser returns exactly:

```text
North
A1\tNorth cell

South
A1\tSouth cell
```

No drawing text exists elsewhere in its model. It emits the generic unsupported
content warning. `odf.py:sheets()` (line 710 at review) iterates `rows(e)`;
`rows()` (534) sends `table:shapes` to unsupported() without descending. The ODT
drawing dispatcher is never reached. This is not a lost Document.text projection
of already-retained data: the drawing text is never extracted.

`paragraphs()` (476) can flatten existing ordinary drawing wrappers when they
occur directly in spreadsheet cells. That is a distinct behavior and location;
this proposed scope must not reroute or duplicate cell-hosted drawings.
`models.py:Sheet` (68) has only name/cells/merges/hidden/dimensions.
`Document.text` (115) emits sheet name plus sorted addressed cells. The API's
`_validate_result` sheet loop (54) validates only those current fields;
`odf.py:_check_visible_text` (795) likewise needs an explicit additive update.

## Additive model and text contract

Add a trailing defaulted field `Sheet.drawings: list[str] = []` using a factory.
Each item is the plain stored text of one supported ordinary drawing, in XML
encounter order within that sheet's direct table:shapes. Use paragraph/list text
joined with newline; preserve explicit spaces/tabs/line breaks using existing
inline rules. This field deliberately does not imply geometry, drawing identity,
visibility, reading order on the rendered page, or a cell anchor. Parent Sheet
provides ownership. Keep duplicate strings from distinct drawings; do not dedupe.

For this narrow subset, retain only nonempty rendered drawing strings. An empty
supported frame representation still wins alternative selection and must not
fall through to another alternative. Do not use whitespace stripping to decide
emptiness: explicit spaces are extracted content. Do not add a second stored
pooled string, drawing names, block trees, or any speculative anchor coordinates.
A list of strings preserves drawing boundaries without a new model class.

Proposed Document.text behavior: keep each sheet's existing name and sorted
addressed-cell lines unchanged, then append its nonempty drawing strings, joined
with the same single newline between entries. Keep the existing double newline
between sheets. Thus files without drawings are byte-for-byte unchanged, while
files with drawings gain the missing text next to their owning sheet. North's
projection begins `North\nA1\tNorth cell\nNorth text-box paragraph\n...` and all
North drawing text precedes the South sheet name. Do not add an A1-like prefix,
modify rows/columns/merges, or put drawing text in Document.textboxes/story_blocks.
No fabricated headings or cell labels are needed.

In JSON, emit `drawings` only for nonempty lists; omit the default field so old
ODS/XLS output remains unchanged. This requires the model owner's explicit
serialization update, alongside the projection and public validation changes.
No universal Sheet.text property or additional cached projection is required.
This extension was subsequently approved and implemented as described below.

## Narrow parser and budget design

* Process only direct `table:shapes` of each top-level spreadsheet table. Do this
  once per sheet, outside row/cell repeat loops. Scope one begins with its direct
  frame/text-box and rect/ellipse/custom-shape children. Groups and drawing links
  can be a separately proved extension; don't use unrestricted descendant search.
* Shape direct children: p/list only, following the proven ODT content gate.
  Text-box scope one: direct p/list (optionally h only after separate coverage),
  with standard list-item/list-header traversal. Unsupported tables, sections,
  nested drawings, and other text-content structures must warn and be skipped,
  rather than silently flattening a broader untested grammar. Ordinary inline
  spans/cached fields and explicit whitespace can use existing inline().
* Frame selection: choose first supported direct text-box, including empty;
  ignore previews/objects/other alternatives and never visit later text boxes.
  Do not reuse the ODT drawing() handler: it pools Document stories and admits
  inline objects. ODS objects remain explicitly unsupported.
* Preserve host row/cell extraction and its warning behavior for other children.
  Avoid leaving a misleading unsupported warning for the now-handled
  table:shapes container: coordinate rows() skip behavior with its new explicit
  consumer, without hiding genuinely unsupported descendants.
* Charge each drawing string once to the shared Budget, including paragraph
  separators, before join/retention. Bound the number of retained drawing records
  with max_records; source XML limits still apply even to empty/skipped drawings.
  Shared cumulative limits must cover all sheets and existing cell/value text,
  not restart for each drawing or sheet. No floating drawing repeats merely
  because rows/columns below it repeat.
* `_validate_result` must add every drawing string once and bound aggregate
  drawing records. `_check_visible_text` must count the proposed exact sheet
  projection, including new separators. Do not double-charge a separately stored
  projection because none is proposed. Public fabricated Document results must
  not bypass text/record limits. No runtime schema or office-reader dependency.

## Required implementation/review tests

1. The authored two-sheet Calc oracle and exact public model/text projection;
   unchanged real A1 values, dimensions and merges; legacy output unchanged when
   drawings are absent. Duplicate text across drawings/sheets remains distinct.
2. All four supported types, lists/spans/explicit whitespace, empty and
   whitespace-only drawings; metadata/geometry decoys and unsupported descendants.
3. Multiple frame text-box alternatives, empty first representation, image/object
   before/after text-box; one representation only, no object/link execution.
4. Repeated rows and columns do not repeat sheet-level drawings; no changes to
   existing cell-hosted drawing behavior. Two sheets with different owning text.
5. Aggregate text/record bounds across drawings and sheets, exact separator
   thresholds, oversized text:s rejected before expansion, unchanged XML depth
   limits, and matching public `_validate_result` budgets.

Scope proof is complete for direct ordinary floating text. The initial triage
changed no production files; the approved implementation follows.


## Implementation

The approved contract is implemented in models.py, api.py and odf.py. The current
Note/NoteBodyRange model and `_validate_notes` logic were preserved; __init__.py
and project version configuration were not changed.

Sheet.drawings is a trailing defaulted list[str]. Empty lists are omitted from
JSON. Document.text appends nonempty drawing strings after the owning sheet's
sorted cell lines, preserving the no-drawings projection and all cell values.
No names, anchors, cells, or second drawing projection are synthesized.

The ODS collector handles only direct table:shapes children of the owning sheet:
frame/text-box and rect/ellipse/custom-shape. Frames pick the first supported
text-box, even if empty. The selected content admits direct p/list and list-item/
list-header traversal, with ordinary inline text rules. Unsupported objects,
metadata/geometry, tables, sections, nested drawings, groups and links are not
scraped. Multiple empty paragraphs retain their newline separators; a single
empty paragraph or empty drawing emits no list item. Explicit whitespace is kept.

Drawing strings and paragraph separators use the shared text Budget before join.
Drawing record counts accumulate across sheets and are checked before retaining
a joined string. A separate running projection size counts sheet names, inter-
sheet separators, drawings, cell addresses, tabs and newlines. Cell repetitions
are preflighted before constructing SpreadsheetCell copies; coordinate lengths
are summed by digit/letter bands, not by walking the repeated cell product.
Existing cell allocation/value/formula budgets remain in place. Sheet-level
drawings are consumed outside repetition loops and cannot become cell values.

The byte-level parser's final visible-text check includes drawings and invokes
public validation when drawings exist. `_validate_result` counts each drawing
string once, enforces cumulative drawing records, and bounds the sheet projection
including separators. Its existing notes checks remain unchanged.

Validation:

* 21 new tests in tests/test_ods_floating_text.py passed: exact authored oracle
  projection, empty JSON compatibility for ODS/XLS, duplicate/whitespace text,
  alternatives, metadata, owner/order, repetition and unchanged cell-hosted text,
  unsupported containers, shared text/record limits, byte-level entry point,
  exact separator thresholds and pre-allocation repeated-cell rejection.
* The 3 original research/schema/Calc checks passed with both optional gates on.
* Ruff passed for all changed Python files.
Independent review: **300 passed, 11 skipped**, including positional model
compatibility, empty JSON omission, ownership and order, alternatives and
shared limits. Its schema check passed; the live Calc reader is an optional
separate check, not a runtime dependency.

The authored package is retained as `tests/fixtures/ods_drawings/floating.ods`
for mutation sampling. Its package contents are checked against the generator;
ZIP timestamps are not semantic expectations.
