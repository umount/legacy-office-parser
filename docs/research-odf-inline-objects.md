# Inline ODF text objects: passive ODT subset

Inline text objects reuse the bounded ODF story reader. The supported subset
extracts stored text and tables without resolving object references.

## Primary evidence

The [OASIS ODF 1.3 Part 3 schema specification, 27 April 2021](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html)
provides the rules used here:

- **§10.4.6.2, draw:object:** an ODF object may be inline as a child
  `office:document`, rather than referenced through `xlink:href`. MathML is a
  different permitted representation and is outside this implementation.
- **§§3.1.2, 3.3, 3.4 and 2.2.3:** the inline document has its own document scope,
  MIME declaration and body. A text document has an `office:text` body. Its
  metadata, settings, styles and scripts are separate from that body.
- **§10.4.1, frames:** content children of one frame are alternative
  representations in preference order. A consumer selects the first one it
  supports. They must not all become concatenated copies of the object's text.
- **§10.4.6.2:** an image preview may accompany an object in the same frame.
  Extracting the object does not require inspecting or decoding that preview.

The [official ODF 1.3 Relax NG schema](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/schemas/OpenDocument-v1.3-schema.rng)
was downloaded for development validation only. In `draw-object`, the schema
chooses between reference attributes, `office-document` and `math-math`.
`draw-frame` permits multiple content representations. Both authored positive
reader fixtures validate with `xmllint --nonet --relaxng` against this schema.
The package parser remains a bounded extractor, not a complete schema validator.

No implementation code from an ODF reader was copied. Runtime has no network,
LibreOffice, UNO or schema-validation dependency.

## Implemented subset and routing

Only an ODT host gains this feature. Recognition requires the exact direct path:

```text
draw:frame / draw:object / office:document / office:body / office:text
```

The object must contain exactly one child, an `office:document`, whose MIME is
exactly `application/vnd.oasis.opendocument.text`. It must have exactly one
`office:body`, containing exactly one body-type child, `office:text`. Template,
master-document, spreadsheet, presentation, chart, MathML, OLE and unknown object
types remain unsupported. A bare `office:text`, a `document-content` substitute,
a duplicate body or an object hidden inside an unknown wrapper is not scraped.

Any `xlink:href` on the object, including an empty value or a package-local path,
excludes it from this subset. No URI, fragment, file or additional archive member
is resolved. Mixed reference/inline representations are conservatively omitted;
a supported sibling fallback can still be selected. Names and URI values are
not echoed in warnings.

The selected embedded body's paragraphs, supported wrappers, nested tables,
cached display fields and nested drawing stories reuse existing traversal.
Object body content goes into the existing `textboxes` string and, when that
pooled key contains a table, `story_blocks['textboxes']`. This is a deliberate
extension of the existing detached drawing-text pool, explained by a warning.
It claims no object identities, anchors, visual placement or chain relations.
Plain-text-only keys retain the existing JSON shape.

Embedded metadata, scripts, settings, style definitions and master pages do not
supply output. No embedded pagination or master-page selection is run, and the
host's master selection never examines this embedded body. Body traversal does
not resolve embedded style names against host styles. Explicit hidden sections
and fields retain the existing filtering behavior; arbitrary style-based visual
visibility, clipping and document rendering remain outside scope.

An embedded document begins a new note-nesting scope. Its notes may be collected
even when the object is in a host note. The host's `in_note` guard is restored in
`finally`, so this does not permit nested notes in the surrounding host story.
Nested object documents still share the same extraction budgets and output pools.

## Alternatives and duplicate prevention

ODT frame traversal selects one direct supported representation, in source order:
a `draw:text-box` or a recognized inline text object. An empty supported body
still wins; falling through on empty text would incorrectly extract a different
representation. Unsupported objects/images may be skipped in favor of a supported
text representation. Once selected, later alternatives are not decoded or
expanded. All source XML remains subject to the package reader's XML budgets.

This selection also prevents duplicates between two text-box alternatives in
one frame. It intentionally changes the old behavior that concatenated all such
alternatives. Existing ODF regressions passed without test changes. Equal text
in separate frames is still emitted separately; there is no value-based dedup.
The parser's supported representation set is narrower than a visual office
reader's: choosing an object after an unsupported image is a text-extraction
policy, not a claim that every reader displays that object representation.

## Budget and passive-runtime invariants

There is no recursive package parse and no new `Budget` or `_Parser` per object.
The already parsed XML tree enforces source characters, node count and depth
across nested document boundaries. `story()`, `table()`, `repeat_stories()` and
`_validate_result` retain the shared cell, text, copied-record and output checks.

Retained structure and legacy string projections are separate costs. Regression
coverage repeats an embedded nested table with two internal rows and two host
columns: 8,000 retained characters plus 4,004 legacy characters. At 12,003 the
parser rejects before a detached story clone; 12,004 succeeds with one clone.
Empty object expansion consumes copied-record budget before detached cloning.
Copies have independent nested cell trees. Source XML and output accounting are
not conflated or reset for embedded documents.

Only `mimetype`, `META-INF/manifest.xml`, `content.xml` and optional host
`styles.xml` are read by the existing package reader. A test includes a bogus
`Object 1/content.xml` and records archive opens to prove it is never inspected.
Stored text is extracted without invoking scripts, macros, link updates, object
activation, subprocesses or office applications at runtime.

## Independent authored-reader confirmation

The positive fixtures are generated by `reader_fixture()` in the new test file.
They are original tiny ODT packages made from literal XML, with no private or
third-party document content. The embedded document contains:

1. Paragraph `Embedded before / Привет`.
2. A table named `Inner` with cell A1 containing `Embedded cell`.
3. Paragraph `Embedded after`.

The host paragraph surrounds the frame with `Host before` and `Host after`.
One fixture has only the inline object; the other adds a one-pixel image preview
as the next alternative. The package has no referenced object subpackage.

LibreOffice **7.4.7.2** opened both original packages read-only in an isolated
profile. The reader used UNO's `NEVER_EXECUTE` and `NO_UPDATE` constants, not
numeric guesses, and accessed the embedded Writer model through
`EmbeddedObjects.getByName(name).Model`. It reported:

```json
{
  "host": "Host beforeHost after",
  "objects": [{
    "text": "Embedded before / Привет\nEmbedded cell\nEmbedded after",
    "cells": {"A1": "Embedded cell"}
  }]
}
```

This confirms actual embedded Writer text and table identity, not a string scan
of XML or the preview. Parser expectations are authored literals, not values
generated from parser output. The optional test launches LibreOffice only for
development; normal tests and runtime do not require it. This is a stored-content
oracle, not a rendered-page comparison or a proof of Microsoft interoperability.

Stable SHA-256 of `content.xml` (ZIP timestamps are not used as identity):

- Without preview: `79f25753f3f8ca64c5ef1e1896fe9bed4047acb20a542076291effa934126ff6`
- With preview: `3d74a79eb07d1763df23a1e2f81a2c0df82f9ad411af58bd851dae935f83ec3d`

Reproduce with an official schema downloaded separately and system Python with
UNO available:

```sh
ODF13_SCHEMA=/path/to/OpenDocument-v1.3-schema.rng \
ODF_INLINE_LO_ORACLE=1 PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_odf_inline_objects.py
```

The oracle needs permission for an isolated local LibreOffice IPC connection.
No external/private documents are used. `reader_fixture()` makes the originals;
the optional test contains the complete reader invocation and cleanup.

## Remaining boundaries

Package-local embedded documents, external references, OLE, MathML, embedded
spreadsheets/charts and ODS/ODP host traversal need separate review. General ODT
shape text and image-attached text are also separate gaps. This change does not
add arbitrary descendant scraping or widen those formats' extraction paths.

## Validation run

- ODF regression suite with the official schema enabled: **239 passed, 3 skipped**
  (the independent reader was run separately; existing optional ODF oracles kept
  their normal skip conditions).
- Complete new suite with the official schema and isolated LibreOffice enabled:
  **42 passed**, including both original positive reader fixtures.
- Ruff passed for the two executable files changed by this feature.
