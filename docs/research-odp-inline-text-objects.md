# ODP inline text objects: slide-owned display projection

## Scope and evidence

This increment applies the existing direct inline ODF text-document recognition
to frame alternatives on presentation slides. The normative path is
`draw:frame / draw:object / office:document / office:body / office:text`.
[ODF 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html)
sections 10.4.1 and 10.4.6.2 define frame alternatives and inline objects;
sections 3.1.2 and 3.3 define document scope and body. The validator and evidence
for the direct text-document subset are described in
[the ODT object research](research-odf-inline-objects.md).

Only an exact text MIME and one unambiguous body are recognized. Any object
`xlink:href`, including an empty or package-relative reference, excludes this
subset. Unsupported MIME, malformed ownership and unknown wrappers are not
scraped. No additional ZIP entry or URI is opened.

## Output and ownership

The selected object's supported paragraphs, lists, tables and block drawing
frames contribute to the owning slide's current text destination. A title frame
keeps its destination; an object in presentation notes stays in slide notes.
The embedded document's presentation attributes cannot reclassify host output,
and nested presentation-notes elements are rejected. Object text is not also
copied to the document-wide textbox pool.

The first supported direct frame representation wins even when empty or hidden.
Equal text in separate frames is retained separately. Embedded style scopes are
already isolated by the shared ODF parser; object metadata, scripts, settings and
master pages are outside the selected body. No layout or object identity is
invented. `odf_inline_text_object_projected_to_slide` records this projection.

This is a bounded display-text increment, not full embedded Writer extraction.
ODP's existing paragraph-anchored drawing and footnote omissions remain diagnosed;
no new pooled footnote model or slide-object structure is introduced. Table
projection follows the existing ODP tab/newline convention. Hidden paragraph
text can leave an empty paragraph separator, as in other slide text.

## Bounds and original tests

The same parser, XML tree, source/record/depth limits, cell budget and retained
text checks apply across object boundaries. There is no recursive package parse
or fresh budget. Later unselected alternatives are not expanded, but their XML
still consumes source budgets. Tests cover literal text/table output, frame
preference including empty bodies, nested frames, independent equal objects,
embedded destination isolation, foreign MIME and ambiguous bodies, all reference
forms, style scope, shared cell limits and unselected deep XML.


## Original reader probe and its negative result

`tests/fixtures/odp_inline_objects/` contains an original ODP and a matching ODT
control, source builder, isolated UNO reader and saved literal observations.
Both packages' content, styles and manifest pass the official ODF 1.3 Relax NG
schemas. The independent XML-path regression reads only the embedded text body
and verifies literal paragraph/cell text before checking parser output.

LibreOffice **7.4.7.2 40(Build:2)** opens the ODP as one page with **zero shapes**;
it exposes no embedded Writer model. The same inline object in the ODT control
is recognized: one Writer model, text `Object before\nObject cell\nObject after`,
one table with A1 `Object cell`. Loading uses read-only mode, `NEVER_EXECUTE`,
`NO_UPDATE`, a fresh profile and no external resources.

This is a schema-valid source construct and a demonstrated import omission in
that reader, **not positive LibreOffice parity evidence for ODP**. The supported
projection rests on normative document ownership, independent source inspection
and literal tests. Other reader versions and arbitrary embedded documents have
not been validated. Run `reader.py` with a system Python providing UNO to repeat
the observations; the runtime parser never launches this helper.
