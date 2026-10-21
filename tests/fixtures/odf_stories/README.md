# Synthetic ODT text boxes and master-page stories

All input XML and prose were authored from scratch for this project on
2026-10-21. These original fixtures and expectations are available under the
repository's Apache-2.0 license. No private documents or external document corpus
were used. LibreOffice output below is derived exclusively from this fixture.

## Files and independent expectation

- `stories.odt`: minimal ODT with Cyrillic main text, three text boxes (in a main
  paragraph, a table-cell paragraph and a header), a two-paragraph header and
  one-paragraph footer. The first stored master is deliberately unused and has
  unique `unusedmaster_header`/`unusedmaster_box` markers. The first body paragraph
  references an automatic style inheriting through two common styles to the used
  master. A paragraph style requests a page break before the final main paragraph.
- `content.xml`, `styles.xml`, `manifest.xml`: exact readable archive sources.
  The ZIP contains only those XML members and `mimetype`, stored first without
  compression. ZIP timestamps are fixed to 2026-01-01.
- `expected.json`: manually authored expectations, independent of parser output:
  three main paragraphs, four text-box paragraphs (main first, then header),
  three header/footer paragraphs; no `unusedmaster` markers.
- `lo/document.xml`, `lo/header1.xml`, `lo/footer1.xml`: unmodified relevant DOCX
  parts from LibreOffice 7.4.7.2, `40(Build:2)`, conversion on 2026-10-21. No user
  profile, generated DOCX metadata or external document is included.

Before this change, the parser retained only the three main paragraphs and
returned empty `textboxes` and `headers_footers`, with unsupported-content and
master-page warnings. The ordinary inline text boxes were lost. Direct text-box
children of table cells could instead be flattened into cell text; a separate
regression test now prevents this misplaced extraction.

After the change, main text and both detached story fields match the independent
expectations and the selected LibreOffice DOCX text exactly. No whitespace
normalization or digit stripping is used in this comparison.

## LibreOffice comparison

The DOCX stores each frame twice in `mc:AlternateContent`: DrawingML in `mc:Choice`
and a VML fallback. The fixture comparison explicitly selects one branch, then
routes `w:txbxContent` away from parent paragraph text. A naive descendant text
walk would duplicate text boxes and include them in main text. Header/footer XML
is read once per saved part, not once per rendered page. The comparison helper
reads `w:t`; this fixture contains no authored tabs, line breaks, custom citation
markers or fields. It is not a general DOCX extractor.

Normal tests compare the saved XML and independent JSON without launching LO.
A live conversion test is available with:

```sh
ODF_STORIES_LIBREOFFICE=1 .venv/bin/python -m pytest tests/test_odf_stories.py -q
```

Each conversion uses its own temporary `-env:UserInstallation=file:///...` profile,
`--headless --convert-to 'docx:Office Open XML Text'`, a 45-second timeout and
process-group termination on timeout. Generated DOCX files stay in temporary
storage. LibreOffice may require execution outside a restrictive sandbox.

## Extraction semantics and limits

ODT frames/text boxes under supported block or inline containers, including
sections, lists, groups, drawing links, table cells, note bodies and header/footer
bodies, are routed to `Document.textboxes`. Text-box text is not also inserted in
main, cell, note or header/footer text. Nested text boxes are pooled in encounter
order, with the outer story before its nested stories. Distinct equal-text boxes
are retained; no text-based or name-based deduplication is performed. Drawing
objects/images and extension metadata are not scraped as fallback text.

Main content is extracted first, followed by stories from selected master pages.
Consequently pooled text boxes, footnotes and endnotes put main-body stories
before header/footer stories. Each selected master is read once in first-use
order; default, left and first variants are pooled in definition order with an
explicit warning that variant identities/page anchors cannot be retained or
resolved without layout. `style:display="false"`/`"0"` variants are skipped.

## Master-page selection and specification basis

The selector follows paragraph/heading and outer-table style references in the
visible main flow, including supported block wrappers. It resolves content.xml
automatic styles, common styles and same-family common parent chains. Default
style break properties are inherited; paragraph-style `next-style-name` is an
editing hint and does not activate another master. References inside cell
paragraphs, frames, notes, annotations, revisions and hidden sections do not
activate main-document masters. Automatic styles in styles.xml are not used as
main-body styles. Unreferenced definitions never contribute extracted stories.

An explicit initial master wins over the first stored master. Without one, the
first page-sequence master is used if present; otherwise the first stored master
is an implementation-defined fallback, reported in a warning. Later explicit
references switch masters without retroactively replacing the initial selection.
Missing/duplicate masters and missing, duplicate, cyclic or conditional style
references warn and omit affected stories, never dump all masters.

The selector advances a master `next-style-name` chain only at explicit inherited
page breaks or saved `text:soft-page-break` markers. No next name means the same
master. Before/after page breaks at the same paragraph boundary are coalesced;
a trailing break-after alone does not prove another page. Alternating cycles do
not re-extract stories. Inheritance depth and the distinct next-master chain are
bounded by `min(max_depth, 256)`; source traversal is bounded by XML node limits.
Page-sequence entries beyond the initial master require represented transitions.

Sources checked for these decisions:

- [ODF 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html),
  sections 5.2, 19.501, 19.503.2–3 and 19.510: paragraph/table master references,
  ignoring paragraph master references inside tables, page versus paragraph
  next-style semantics, and common-style parent/default inheritance.
- [OASIS OFFICE-3461](https://issues.oasis-open.org/browse/OFFICE-3461): initial
  master selection without an explicit reference is implementation dependent.
  The first-stored fallback is this parser's documented choice, not a normative
  guarantee or a hardcoded preference for a style named Standard/Default.

No automatic overflow/layout engine is implemented. Saved soft breaks may be
stale; next masters reached only by unrecorded overflow can be omitted, with a
warning. Precise page-sequence reconciliation with explicit style switches and
parity-dependent variants is not claimed. The selected-master set is conservative;
this is not a claim of complete active-layout or LibreOffice rendering parity.
Warnings also state that text-box anchors/linked-frame flow are not retained.
Direct master-page drawing objects outside header/footer bodies and extension-
namespace header/footer variants remain unsupported.

Repeated ODT rows/cells clone all extracted stories in row-major order, including
notes in frames. Text, separator and table-cell budgets include those copies.
XML depth/node budgets apply across content and styles; nested notes remain
unsupported even through an intervening frame. Hidden fields, annotations,
tracked-change containers, covered cells and `text:section text:display="none"`
subtrees are not searched for stories. Hidden-section exclusion is shared by
main/story extraction and master selection.

Additional unit tests cover nested/empty frames, multiple paragraphs, lists,
tables, explicit whitespace, notes in both directions, repeated cells/rows,
master references/inheritance, first/next behavior, ambiguous references, main-first
story order, hidden sections, variants, resource limits, and unchanged ODS/ODP
routing. The LO fixture validates inherited selection and omission of the unused
first master as well as ordinary stories, not every synthetic edge case.
