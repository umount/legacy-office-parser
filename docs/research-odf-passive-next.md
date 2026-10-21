# Next passive ODF scope: shape text first

Initial research, 2026-10-21. The follow-up implementation below adds ODT `draw:rect`,
`draw:ellipse`, and `draw:custom-shape` paragraph/list text using the bounded drawing-story reader. The authored shape fixture passes
ODF 1.3 schema validation and LibreOffice 7.4.7.2 independently reads every label.
Image-attached text and ODS/ODP inline Writer objects remain deferred: these probes
do not establish successful independent-reader support.

## Primary evidence

Use the [OASIS ODF 1.3 Part 3 specification](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html)
and [official Relax NG schema](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/schemas/OpenDocument-v1.3-schema.rng).
Relevant clauses: rectangle 10.3.2, ellipse 10.3.9, custom shape 10.6.1,
frame alternatives 10.4.1, image 10.4.4, object 10.4.6.2, table shapes 9.2.8.
The schema definitions `draw-rect`, `draw-ellipse`, and `draw-custom-shape`
reference `draw-text`, which permits zero or more `text:p` or `text:list` children.
It does not permit direct `text:h` or `table:table` children. `draw-image` also
references `draw-text`; the specification says this text accompanies the image.
Frame children are alternative representations in preference order, so adding
image support must not concatenate every alternative. `draw-object` admits an
inline `office:document`; `table:shapes` contains shapes without assigning cells.

Schema acceptance establishes grammar, not complete conformance or independent
implementation support. In particular, the ODS/ODP negative observations below
must not be described as proof that inline documents are forbidden.

## Reproducible original probes

`tests/test_odf_passive_research.py` authors four tiny ZIP packages entirely from
literal XML. It reuses namespace, paragraph/table, and embedded-document builders
and the authored one-pixel PNG from `test_odf_inline_objects.py`. No downloaded or
private document is used. The embedded Writer body is `Object before`, table
`Inner` cell A1 `Object cell`, and `Object after`. No href, scripts, or listeners.
The ODP has a named master and matching styles.xml entry, rather than an unresolved
master reference. Four content XML files pass the official ODF 1.3 schema.

Run from the repository root (schema downloaded once for development only):

```sh
PYTHONPATH=src:tests .venv/bin/python tests/test_odf_passive_research.py /tmp/odf-passive-research
ODF13_SCHEMA=/tmp/odf-inline-evidence/schema.rng .venv/bin/python -m pytest -q tests/test_odf_passive_research.py
/usr/bin/python3 /tmp/odf-passive-research/reader.py /tmp/odf-passive-research
ODF_PASSIVE_RESEARCH_LO=1 .venv/bin/python -m pytest -q tests/test_odf_passive_research.py
```

The generated reader uses an isolated LibreOffice profile and private UNO pipe,
read-only hidden loads, `MacroExecMode.NEVER_EXECUTE` and `UpdateDocMode.NO_UPDATE`.
It closes documents and terminates the process. This is a development oracle, not
a parser dependency. Optional pytest verifies literal expected shape labels;
it does not freeze current parser omissions or reader limitations as requirements.

Observed results:

* `shapes.odt`: Writer imports RectangleShape, EllipseShape, and CustomShape with
  strings `rect paragraph\nrect list`, `ellipse paragraph\nellipse list`, and
  `custom-shape paragraph\ncustom-shape list`. Host body is `Host beforeHost after`.
  Before shape support, the parser returned only that host body; the supported shape labels are now extracted separately.
* `image.odt`: Writer imports graphic `AttachedImage` (DrawPage FrameShape), but
  exposes no attached paragraph/list through the inspected shape, host body, or
  TextFrames collection. Current parser returns empty text. This is not a positive
  reader oracle for image text, despite the positive schema evidence.
* `inline.ods`: Calc loads the document but its sheet DrawPage has zero objects.
  Parser returns `Sheet1\nA1\tHost cell` and omits the inline object.
* `inline.odp`: Impress loads the document but its first DrawPage has zero objects.
  Parser returns empty text and omits the inline object.

These are model-level reader observations, not rendered visibility claims. The
reader emits JSON so another reader/version can be compared without relying on
our parser's expectations. The next step for the deferred features is a second
independent reader or a reproducible successful import into these document types,
not following package references as a workaround.

## Exact current paths and risks

Locations in the reviewed source (line numbers can move):

* `odf.py:17`, `inline():119`, `blocks():639`, `drawing():280`: `DRAW_STORIES`
  accepts frames/textboxes/groups/links, excluding ordinary shapes and images.
* `paragraphs():463–479`: ordinary shapes are generic recursive wrappers. This
  creates an inconsistency: a direct rectangle with paragraph `Shape label` returns
  no text at the ODT body, but inside a table cell returns cell text `Shape label`.
  Merely adding shape tags to one caller would leave gaps or duplicate text.
* `drawing():250`: ODT frame selection already chooses one supported representation;
  `inline_object_body():228` checks direct text-document MIME/body and rejects href.
  Shape text should not change those object-selection rules.
* `sheets():697` visits rows, while `table:shapes` is unsupported. Cell paragraph
  traversal can descend into existing shape wrappers, but not inline draw:object.
* `slides():737` checks SKIP before descending; object and image are skipped.
  It traverses all supported frame children, so ODP does not yet have the ODT
  alternative-selection guarantee. It directs content into title/text/notes.
* `models.py:115` Document.text renders only cells/sheet names for ODS and slide
  fields for ODP. Adding Document.textboxes/story_blocks in those formats would
  not make the text visible. Do not fabricate A1 anchors for floating sheet text.

## Proposed narrow ODT design

1. Introduce a small explicit set of the three proven shape names. Route it through
   all ODT drawing entry points: inline paragraphs, body blocks, cell paragraphs,
   groups and drawing links. In drawing(), collect only direct allowed p/list
   children as a detached `textboxes` story. Do not scrape svg:title/desc, event
   listeners, geometry, object metadata, or arbitrary descendants. Nested valid
   drawing constructs inside those paragraphs follow the existing traversal once.
2. Keep shape text out of host paragraph/cell text and emit it once in the pooled
   story. This deliberately makes direct-cell shapes consistent with existing
   textboxes; document that observable change. Preserve source order within the
   pool, without inventing anchoring/layout. Do not activate story_blocks merely
   for new pure-text shapes; if another sink has a table, retain these paragraphs
   across all sinks of the existing key under the integrated story policy.
3. Reuse the shared Budget and story()/repeat_stories() paths. Never allocate a
   fresh parser or budget per shape. Preserve XML depth/node checks, inline text
   expansion limits, recursive table/record accounting, and public
   `_validate_result` costs for retained blocks plus legacy strings. Empty shapes
   and empty paragraphs must retain existing zero/empty semantics.
4. Tests: all three shapes in p/body/cell/group/link/note/header; mixed shape and
   textbox/object source order; metadata decoys; repeated cells/rows with shape
   text; mixed table-bearing story keys; expanded text:s at exact limits; rejection
   before detached clones; empty shapes and empty list paragraphs; unsupported
   direct tables/headings not recursively accepted; no href follow or execution.
   Keep the independent Writer fixture as the positive external oracle.

## Conditional later designs

Image-attached text: collect only p/list children, without decoding image data or
fetching its URI. First resolve whether a text-bearing image counts as a supported
frame representation: choosing it should suppress later alternatives; an image
with no textual body must not accidentally hide a supported inline object. Test
image-first/object-first and empty variants. Current reader probe is insufficient
for implementation under the requested evidence gate.

ODP inline text: reuse the strict direct office:document/body/text eligibility
check, but introduce a scoped text-document collector sharing the host budget.
The ODT format gates in inline(), notes, and cell processing mean blindly calling
story() from slides() is insufficient. Flatten paragraphs/tables once into the
current slide destination, with proper document-local notes/style scope. Host
placeholder class selects destination; embedded styles/classes must not leak
into host title/master selection. Apply first-supported frame selection and count
all output separators, expansion, depth, notes, and repeated tables before copies.
Require successful independent-reader evidence before implementing.

ODS inline text: a sheet-floating object needs a sheet-associated text/story output
contract, including ordering, serialization, and public validation. This requires
model/API agreement outside odf.py. Cell placement/geometry is not evidence that
object text is the cell's value. Defer rather than dropping it into invisible
Document.textboxes or fabricated spreadsheet coordinates. Independent-reader
support remains an additional prerequisite.

No runtime schema, network, links, archive-subdocument traversal, or macros are
introduced. Before this implementation, the research baseline odf.py SHA-256 was
`8a6f0b8e419b1dcbad5603247048cca80003fc318ebd7be2adc9c390fdd5f962`.


## Implemented follow-up: ready for independent review

`odf.py` now includes the three proven names in `TEXT_SHAPES` and ODT
`DRAW_STORIES`. All existing ODT dispatch points therefore route them to
`drawing()`, including the simple-cell paragraph path and structured-cell block
path. The shape handler filters direct children to `text:p` and `text:list`, then
passes those original elements to the existing `story()` collector. It does not
copy XML, recurse into metadata/geometry containers, reset budgets, or add a
format-wide descendant search. Shape text is pooled with the existing textboxes
warning and serialization policy. ODS/ODP behavior remains outside this change.

Direct-cell shape labels now leave cell values and appear once in textboxes;
this is the intentional consistency change. Invalid direct shape children of
frames do not become supported frame alternatives. Shapes inside a selected
textbox are extracted; shapes inside later alternatives are not visited.

`tests/test_odf_shapes.py` contains 39 checks covering all three shapes and eight
routing locations, allowed content and metadata decoys, existing structured-story
projection, selected alternatives, nested shape text, empty semantics, repeated
rows/cells, and limits. It tests rejection before detached cloning at 12003
characters with repeated nested table stories (12004 passes), and at 4001 with
retained shape paragraphs plus legacy strings (4002 passes). Empty repeated
paragraphs are also bounded before cloning. A parser assertion consumes the same
schema-valid authored shape document as the independent reader.

The existing `test_odf_passive_research.py` oracle remains unchanged. It asserts
positive LibreOffice shape labels, not missing parser behavior, and can be enabled
in CI with `ODF_PASSIVE_RESEARCH_LO=1` on a runner providing LibreOffice, system
Python UNO, and local IPC. All six research checks passed with the official schema
and independent reader enabled. The focused shape/API/security run passed all
62 checks. Original observations above describe the pre-implementation baseline.
