# ODP / OTP

## Supported

- Slide order, title/body/notes, hidden flags and text/table projections.
- Each frame selects its first supported textbox, table or direct inline ODF
  text document. Empty/hidden selections do not fall through to another copy;
  identical text in independent frames stays distinct.
- Inline text objects remain in the owning slide's destination, not pooled
  textboxes. Embedded styles are isolated; presentation attributes inside an
  embedded text document cannot reroute host content.
- Inline footnote/endnote bodies and paragraph-anchored drawings follow their
  enclosing paragraph in the same slide destination. Citation labels are omitted;
  repeated table cells retain repeated content under shared limits.
- Empty presentations and missing optional styles/metadata are accepted.

## Limits and remaining work

Object identity/layout, images, external or package-linked objects and other
embedded formats are not extracted. Any `xlink:href` excludes inline-object
recognition, even an empty or package-local reference.

## References and reader boundary

- [ODF 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html): §10.4.1 frame alternatives, §10.4.6.2 inline objects and §3 document/body scope.
- [ODF packages](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part2-packages/OpenDocument-v1.3-os-part2-packages.html).

Tests are in `tests/test_odp*.py`. The original
`tests/fixtures/odp_inline_objects/inline.odp` is schema-valid, but LibreOffice
7.4 imports it with zero shapes; its matching ODT control exposes the Writer
model. This is a documented reader omission, not a positive ODP parity claim.
The fixture's builder, reader and observations remain beside it.
