# ODT / OTT

## Supported

- Ordered paragraphs, explicit heading levels, nested tables, merges and lists
  flattened in source order. No generated list numbering is invented.
- Notes and structured auxiliary stories; supported hidden/deleted content is
  filtered. Missing optional styles/metadata do not block body text.
- Selected header/footer masters from evidenced main-flow styles/transitions;
  no inferred pagination. Embedded documents have isolated style scopes.
- Cached index/bibliography entries and index titles; generation instructions are ignored.
- Textboxes and supported ordinary shapes, including captions. A frame selects its first supported
  representation even when empty or hidden.
- Direct inline ODF text documents contribute to textbox stories. Recognition
  requires exact document/body ownership and no `xlink:href`; notes share budgets.

## Limits and remaining work

Package-local or external embedded references are not opened. OLE, MathML,
charts, images, unknown extensions and implicit page layout remain unsupported.
The parser does not execute scripts or evaluate conditions/fields.

## References

- [ODF 1.3 Part 3](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html): §3 document scope, §5 headings, §10.4 frames/objects, §16 styles, §19.510 inheritance.
- [ODF packages](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part2-packages/OpenDocument-v1.3-os-part2-packages.html): MIME, manifest, encryption and ZIP structure.

Tests are in `tests/test_odf*.py`; inline-object fixtures have literal source
expectations and an optional read-only LibreOffice probe. See
[ODF contract](OUTPUT_FORMAT.md#opendocument-detection-mime-types-and-templates)
and [provenance](../THIRD_PARTY.md). ODS and ODP have separate coverage pages.
