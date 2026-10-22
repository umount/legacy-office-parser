# ODP frame alternatives: one owner per frame

## Scope and evidence

This change is isolated to ODP slide traversal in `odf.py`. It does not add
embedded-document extraction, image text, external resource access, new output
fields, or renderer visibility claims.

Primary evidence: [ODF 1.3 Part 3, section 10.4.1, General](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html).
Frame content children are alternative representations of one content item;
their order expresses the author's rendering preference. Section 10.4.2 lists
both `draw:text-box` and `table:table` among frame children. The normative
[Part 3 document](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html)
contains both cited sections.

The specification establishes alternative ownership and preference order.
Choosing the first *supported text representation* is this extractor's bounded
policy, already used for ODT frames; it is not a claim that an office renderer
will select the same representation. In particular, an earlier image can be
skipped because this parser does not interpret image content.

## Before and after

Previously `slides.walk` recursively visited every child of a `draw:frame`.
Two alternative text boxes therefore produced two slide text fragments, even
when they represented identical content. ODT `drawing()` already selected only
one supported representation, including an empty one.

ODP now selects the first direct `draw:text-box` or `table:table` in source
order. These are the existing supported text-bearing frame representations.
Unknown/unsupported children before it retain existing diagnostics and do not
become text sources. After selection, remaining alternatives are not traversed.
A frame without supported content emits no text. Invalid frame-child containers
are not recursively scraped merely because the generic slide walker recognizes
their tag elsewhere.

Selection depends on element type, not on resulting text. An empty text box,
empty table, or text box whose paragraphs are hidden/deleted still owns its
frame: later alternatives do not escape. Errors and limit failures in selected
content propagate rather than triggering fallback. Existing title/body/notes
routing is passed into the selected child, with notes retaining precedence over
title classification. The existing hidden-slide metadata behavior is unchanged.

Equal text in distinct frames is preserved once per frame. Nested frames select
independently. There is no global string deduplication. Direct table alternatives
keep the existing row projection; no new table ownership or model is introduced.

## Bounds and validation

The selection scan is linear in the number of frame children and adds no
recursive pass, XML parser, decompressor, or resource resolver. The complete XML
is parsed under existing source character, node, and depth limits, including
unselected alternatives. Only selected content incurs expansion/output/cell
charges. Existing final rendered-text accounting still includes separators
between independent frames. This distinction is tested with exact thresholds.

`tests/test_odp_frame_alternatives.py` contains only original synthetic XML/ZIP
inputs. Coverage includes text and table alternatives in both orders; empty
selection; unsupported first and unsupported-only frames; metadata; identical
independent frames; title/body/notes routing; hidden and deleted first content;
hidden ancestors and hidden slide metadata; nested frames; skipped hostile
expansion; selected cell limits; source/node/depth limits; and exact output
limits including independent-frame separators.

No independent office-renderer comparison is claimed. This is an ownership
correction justified by the primary format rule and tested through the public
parser, not a layout/rendering implementation. ODT and ODS collectors, passive
embedded objects, and the diagnostic registry remain unchanged.

Validation:

- Dedicated regression module: **29 passed**.
- `pytest -q tests/test_odp_frame_alternatives.py tests/test_odf*.py tests/test_ods*.py`:
  **567 passed, 11 skipped**. Skipped checks are not claimed as executed evidence.
- Ruff on the changed parser and new test module: **passed**.
