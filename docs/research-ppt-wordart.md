# PPT stored WordArt text

Implemented 2026-10-21, independently from the specifications below. No POI code,
Office renderer, ZIP/XML interpreter, or new runtime dependency is included.

## Sources and decisions

- [MS-ODRAW 2.3.22.1 gtextUNICODE](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/3b9a1a7b-ad49-410c-bb32-ab91decff765)
  identifies geometry text as property `0x00C0`. Its complex bit selects stored
  bytes; its value is a byte length, and fBid is ignored. A non-complex value must
  be zero. [2.3.22.2](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/c2dfbfd1-9652-40c2-a8d2-1f292bae61b5)
  defines the complex value as a null-terminated Unicode string.
- [OfficeArtFOPT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/10dc2fe1-9e69-48dc-a1d1-2921dfb9c28e)
  and [OfficeArtRGFOPTE](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/a7ea6419-bdb8-4faf-844d-fa4acbeb9ecd)
  establish the property table and its separate complex-data area. The parser
  walks six-byte descriptors first, then advances through complex values in
  descriptor order. Unknown properties are bounded and skipped, never searched
  for strings. Fonts, shape names, descriptions and other metadata are not body
  text.
- [MS-PPT 2.9.76 OfficeArtClientTextbox](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/f50070dd-a4dc-4edd-a446-c4fcc5c80ace)
  specifies the existing native text path: either an outline reference or text
  atoms with supporting records. That path stays intact, including its title
  classification and outline-reference validation.
- POI primary sources checked: [EscherPropertyFactory](https://github.com/apache/poi/blob/trunk/poi/src/main/java/org/apache/poi/ddf/EscherPropertyFactory.java),
  [EscherPropertyTypes](https://github.com/apache/poi/blob/trunk/poi/src/main/java/org/apache/poi/ddf/EscherPropertyTypes.java),
  [EscherArrayProperty](https://github.com/apache/poi/blob/trunk/poi/src/main/java/org/apache/poi/ddf/EscherArrayProperty.java),
  [HSLFTextShape](https://github.com/apache/poi/blob/trunk/poi-scratchpad/src/main/java/org/apache/poi/hslf/usermodel/HSLFTextShape.java),
  and [HSLFMetroShape](https://github.com/apache/poi/blob/trunk/poi-scratchpad/src/main/java/org/apache/poi/hslf/model/HSLFMetroShape.java).
  These corroborate the descriptor/complex ordering, property ID, and the
  distinction between a native text shape and an alternative Metro shape.
  Legacy pVertices/pSegmentInfo lengths can exclude their six-byte array header;
  the bounded skip handles that convention, including compressed element sizes.
  It does not construct or render geometry.

## Scope and duplicate policy

Only FOPT directly belonging to an OfficeArtSpContainer reached through an active
slide or linked notes is a WordArt source. Drawing-group defaults, masters,
unreferenced notes/slides, old replaced objects and arbitrary record payloads are
not searched. Nested group shapes retain drawing order. Geometry text becomes a
body block (kind 1); `Slide.text`, `Slide.title`, notes and model definitions are
unchanged. There is no attempt to infer a title from WordArt position or size.

Native text is emitted first within a shape. Equal normalized geometry text is
suppressed only if that same shape has matching native text or a validated
outline reference to it. Distinct attached text survives. Identical text on
separate shapes survives, even when it matches an unrelated outline block. All
stored geometry strings consume the shared decoding budget before suppression.
This deliberately narrow equality rule avoids duplicating a same-shape fallback
without globally removing legitimate repetitions.

## Native extensions investigated

[metroBlob, MS-ODRAW 2.3.4.41](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/0505b55f-f58a-4166-b574-83785d1035c1)
is alternative DrawingML packaged as OPC, not another native text run. The spec
recommends ignoring it; POI delegates its interpretation to its separate OOXML
implementation. We detect nonempty Metro data in live FOPT/TertiaryFOPT and warn
once, without opening the package or combining it with native text. This avoids
both fallback duplication and introducing a general OOXML extraction subsystem.
Extension-only text therefore remains an explicit limitation.

[SecondaryFOPT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/a7b26490-a8c7-4087-904e-417b10839f77)
is associated with the movie property;
[TertiaryFOPT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-odraw/a687e90c-1748-4f57-8758-be31cfb36185)
includes Metro data and geometry-font metadata. Neither is treated as an
additional WordArt text source. [PFMasks](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-ppt/2a02831a-088b-44e7-84c9-c185ab314a71)
controls paragraph formatting for TextPFException/9, not additional text. No
sufficiently established separate native extension text source was added.
Existing slide extension warnings remain. Rendering, embedded objects and OCR
are outside this implementation.

## Bounds and malformed input

Property counts consume the shared record budget before iteration. Descriptor
and complex lengths must fit their record, with no unclaimed trailing bytes.
Duplicate geometry properties/tables are rejected. UTF-16 uses the existing
strict decoder and shared conservative code-unit budget before slicing/decoding;
terminators, controls and surrogate pairs count. Odd lengths, missing terminal
NUL, embedded NUL followed by more content, and isolated surrogates fail closed.
Existing depth and emitted-output limits still apply. Skipped unknown complex
values are not allocated or decoded. No stale-data recovery is introduced.

## Independent regression and real fixture

`tests/test_ppt_wordart.py` uses wire-format builders and literal expected values.
It covers grouped WordArt, Cyrillic/CJK/non-BMP text, breaks, metadata offsets,
fBid, empty/default properties, same-shape native and outline duplicates,
repeated distinct shapes, active edits, dead masters/slides, linked notes,
malformed tables/lengths/UTF-16, legacy array lengths and shared budgets.

An original real PPT was authored through LibreOffice UNO, saved with the
`MS PowerPoint 97` filter, closed, then reopened through UNO. It contains three
Fontwork wave shapes with these authored strings:

```text
WordArt original / Привет 世界
Repeated WordArt
Repeated WordArt
```

LibreOffice **7.4.7.2 40(Build:2)** read those exact three strings back. The parser
returned the same body, one slide, empty title and empty notes. Disabling only
geometry-property extraction returns empty text, proving this fixture exercises
the omission instead of merely retesting TextCharsAtom fallback. The existing
extension warning occurs for LibreOffice's slide extensions and is not a text
mismatch. This is a text comparison, not a claim of visual fidelity or testing
against Microsoft PowerPoint.

The unmodified 459264-byte CFB file is stored as zlib/base85 in the test module to
respect the requested file scope. Its SHA-256 is
`2d0a5dac9bd229a57e382a075bbe362bdf291e5933298593029d9d54eddc007d`.
It contains only newly authored test content, not a third-party document. Normal
regressions need neither LibreOffice nor UNO. To recover the real fixture:

```bash
PYTHONPATH=src:tests .venv/bin/python - <<'PY'
import base64, zlib
from pathlib import Path
from test_ppt_wordart import _ORIGINAL_PPT
Path('/tmp/original-wordart.ppt').write_bytes(zlib.decompress(base64.b85decode(_ORIGINAL_PPT)))
PY
```

To regenerate equivalent content, start an isolated LibreOffice with
`--headless --accept='pipe,name=wordartfixture;urp;StarOffice.ComponentContext'`
and a fresh `-env:UserInstallation=file:///tmp/...` profile. Connect through
system Python's `uno` module. On a new `private:factory/simpress` document, remove
all shapes from page zero. For each of the three strings create
`com.sun.star.drawing.CustomShape`, add it to the page and set:

```python
# prop(name, value) returns com.sun.star.beans.PropertyValue.
shape.Position = uno.createUnoStruct('com.sun.star.awt.Point', 2000, 2000 + i * 4000)
shape.Size = uno.createUnoStruct('com.sun.star.awt.Size', 22000, 3000)
shape.CustomShapeGeometry = (
    prop('Type', 'fontwork-wave'),
    prop('TextPath', uno.Any('[]com.sun.star.beans.PropertyValue',
                           (prop('TextPath', True),))),
)
shape.String = value
```

Save an ODP with `impress8`, then `storeToURL` a PPT using `MS PowerPoint 97`.
Close and reopen the PPT, read `String` from its three shapes, and compare those
literals with the parser's slide body. Generated timestamps and previews may
change binary hashes. The development evidence (ODP, PPT, UNO-read text) is in
`/tmp/ppt-wordart-evidence`; the portable fixture is embedded above.

## Validation

Run `.venv/bin/python -m pytest tests/test_ppt.py tests/test_ppt_wordart.py -q`
and `.venv/bin/ruff check src/legacy_office_parser/ppt.py tests/test_ppt_wordart.py`.
