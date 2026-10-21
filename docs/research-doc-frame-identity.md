# DOC first-cell paragraph-frame identity

## Primary research

[MS-DOC 2.4.3, Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
adds a paragraph-frame boundary criterion when both adjacent rows have default
table position/wrapping. The comparison concerns the first paragraph of each
row's first cell. It is independent of cell grid dimensions.

[Determining Formatting Properties, part 2](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417)
and [Determining Properties of a Style](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/9258b41c-ff0a-4c96-a3a9-610664dabbeb)
establish the style/property sources. The implementation resolves the paragraph
style's base chain, then its direct PAPX and piece modifiers. A direct PIstd
resets the frame properties to those of the selected style; subsequent direct
properties override them.

Operand definitions and defaults:

- [Paragraph Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/484822ee-a9d9-4af4-8423-29fda67a6a58): the twelve frame properties, PIstd reset semantics.
- [PositionCodeOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/4adae037-8747-471a-a1a0-082a5244ebc7): two anchor components; ignore padding.
- [WHeightAbs](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d6ac8221-866a-45a5-8fdc-1d853ccb96de): height magnitude and minimum-height flag.
- [DCS](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d1840469-ec25-456d-af64-87f34da3f0d4): drop-cap type/line count; ignore reserved byte.
- [FrameTextFlowOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/f83fcc14-ab18-4f5f-94fc-a03e00a7d367): three significant bits; backwards flow requires vertical flow.
- [Prm0](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/35226a0b-9038-4427-83c2-3830a8554267): compact PPc, PWr and PFLocked encodings.

## Changes

`_doc_table.py` defines immutable `FrameIdentity` and bounded, normalized operand
decoding. It also supplies `TableIdentity.default_position`; that gate tests
only table anchor/position/wrapping, excluding unrelated TIpgp/style identity.
The default anchor is 0xF0, preserving the previously reviewed TPc correction.

`_doc_styles.py` retains at most twelve effective frame overrides per paragraph
style. The existing hidden-text tuple representation is unchanged. Frame
inheritance is iterative, cached by style index, and checks cycles, parent
references/kinds, record budget and maximum depth. An invalid direct style
selection has default frame properties while awaiting a later valid selection;
the existing final paragraph-style validation remains in force.

`doc.py` applies inherited frame properties before direct properties, handles
PIstd resets, and applies complex/compact piece overrides afterwards. Immutable
frame values participate in existing external-PAPX fallback snapshots.

Each table-depth accumulator captures only its first paragraph in the first
cell, including an empty or hidden paragraph. It never substitutes the row
mark, later paragraphs, another cell, or a child table's paragraph. The row mark
provides the position gate. A confirmed difference closes the previous table,
normalizes its grid and resets vertical merges before attaching buffered cells.
Missing first-paragraph evidence and recovery without a row terminator do not
invent frame boundaries.

No frame layout, text rotation, positioning, or reordering is performed. No
model changes, runtime I/O, network access or external command execution added.

## Validation

`tests/test_doc_frame_identity.py`: **87 passed**. Literal expected trees reuse
existing synthetic stream/stylesheet helpers, never production identity helpers.
Coverage includes all twelve direct and inherited properties; explicit defaults;
child/direct/style-selection overrides; all eight table-position gate fields;
compact and complex piece modifiers; ignored bits; first empty/hidden paragraphs;
later paragraphs/cells/TTP exclusion; nested inheritance and parent isolation;
merge/grid isolation; incomplete rows; external PAPX and fallback; invalid
operands, truncation, style cycles/depth and cell/record limits.

`pytest -q tests/test_doc*.py tests/test_security_side_effects.py`:
**669 passed, 2 skipped** (existing opt-in checks). Ruff passes for all three
changed source files and the new test. Existing test files were not modified.
The earlier deterministic real-OLE identity fixture and its tests remain intact.

## Scope and limitations

This implements paragraph-style inheritance plus direct frame properties.
Table-style/conditional-table-style formatting and list formatting remain outside
the existing parser's supported formatting evaluation. Consequently this is not
a claim of complete effective frame identity for documents whose frame properties
come from those unsupported sources. Existing table-style warnings remain.

Protection-bookmark boundaries and PGPInfo graph validation are still separate
gaps. This change checks operand bounds and relevant bit invariants; it does not
validate every cross-property layout constraint (for example, that a text-flow
operand is accompanied by another nondefault frame property). It compares the
stored semantic values without rendering them.

No private corpus or new LibreOffice frame oracle was used. These are independent
synthetic regression tests, not evidence that LibreOffice agrees with every frame
boundary. The earlier TDxaAbs real-OLE discrepancy remains documented separately.
