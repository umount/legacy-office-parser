# RTF fallback-only shape text: evidence and boundary

## Result

No fallback recovery is implemented. `shprslt` remains suppressed. A separate,
strict explicit WordArt property subset is now implemented in
`src/legacy_office_parser/rtf.py`, as described below. The original probes below do not
establish a safe rule for promoting a legacy fallback when modern shape text is
absent. This is an unresolved extraction gap, not a claim that fallback text is
always redundant or irrelevant.

This investigation extends [the standalone legacy textbox research](research-rtf-legacy-textboxes.md).
It does not reopen linked-story or group ownership. It does not scrape general
shape-property values for text.

## Primary specification

Microsoft's RTF specification, reproduced in the
[Word 97–2000 Drawing Objects section](https://latex2rtf.sourceforge.net/rtfspec_7.html),
describes `shprslt` as the Word 6.0/95 representation of a shape. The first linked
textbox contains the entire story; later boxes may have no `shptxt`. A group's
fallback represents the whole group. Shape properties have defaults when absent.
Consequently, absence of a local `shptxt` alone does not prove an independent
fallback story. Neither an empty primary nor an absent shape identifier supplies
a general ownership rule.

The same primary document defines `gtextUNICODE` as a Unicode text string for
WordArt. `fGtext` enables these properties and defaults to false; `fGtextOK`
indicates WordArt support. Type 136 is plain text. These are separate from
fallback selection.
No reader implementation or third-party fixture was copied.

## Original fixtures and independent conversion

The ASCII RTF inputs in `tests/fixtures/rtf_fallback_text/` were authored directly
for this investigation. They contain literal text and drawing controls, with no
external references, macros, embedded objects, or active content. Expected text
is literal in the tests. Parser output was not used to generate the fixtures or
the LibreOffice expectations.

Observed with **LibreOffice 7.4.7.2 40(Build:2)**, converting RTF to flat ODF:

- `standalone.rtf`: the standalone legacy textbox yields `Legacy control`.
- `modern-primary.rtf`: the modern primary textbox yields `Primary text`.
- `no-instructions.rtf`: no textbox text is exported when the shape has only a
  legacy fallback. This is a boundary probe, not a claim of complete shape syntax.
- `empty-instructions.rtf`: an empty instruction group plus fallback exports no
  textbox text.
- `typed-no-primary.rtf`: explicit textbox shape type 202 without `shptxt` still
  exports no fallback textbox text.
- `empty-primary.rtf`: an empty `shptxt` exports an empty textbox, not the fallback.
- `primary-before.rtf` and `primary-after.rtf`: both export only `Primary text`.
  Reversed ordering is a reader probe, not a claim that every ordering is valid.
- `group-fallback.rtf`: the tested group fallback exports no textbox text.

These are finite observations about this converter version. They do not prove
that all fallback-only shapes lack useful text, that Microsoft Word behaves
identically, or that another LibreOffice version has the same behavior.
`lo-observations.json` records source SHA-256 hashes, converter version, exported
text, and parser observations. Its `all_paragraphs` field also retains XML
indentation whitespace encountered in outer paragraphs; it is diagnostic data,
not a normalized document-text oracle. The tests compare explicit shape text.
Generated FODT files are temporary and are not fixture inputs.

## Conservative behavior and adversarial checks

Fallback text remains omitted whether the primary is absent, empty, before the
fallback, or after it. Group and nested fallbacks remain omitted. No replacement,
duplication heuristic, or fallback buffer has been introduced.

Tests cover suppressed object, picture, information, property, background and
unknown optional ancestors; nested fallback and primary decoys; independent
sibling primary stories; main-table and header preservation; and font/story
controls hidden inside fallback data. These ensure recognized destinations do
not escape parent suppression or mutate another story. Binary payload remains
opaque and length-checked. Oversized skipped text does not consume the retained
text budget, while stream, record and depth limits still apply. This validates
the existing conservative path, not a new fallback decoder.

A recovery implementation would need independent positive evidence and a
bounded ownership rule for the selected subset. Merely buffering a fallback
until shape close would not resolve linked boxes, groups or empty-primary
semantics. No runtime converter or external fetch is proposed.

## Explicit WordArt subset

The initial `wordart-property.rtf` probe supplies literal `Original WordArt` in
`gtextUNICODE` on explicit shape type 136. LibreOffice exports that string in a
`draw:custom-shape/text:p`, while the original parser omitted it. That probe lacks
explicit enable flags: its recorded parser omission is historical, and it remains
outside the accepted subset. LibreOffice's treatment does not override the
specification's disabled default.

The independently authored `wordart-explicit.rtf` adds `fGtext=1` and
`fGtextOK=1`. Its live conversion preserved exactly `Original WordArt`; the parser
now extracts the same text. Both observations and source hashes are retained.

The reader accepts only a standalone `shp` with one immediate `shpinst`, explicit
`shapeType=136`, both enable flags exactly `1`, and a single `gtextUNICODE`.
The inherited effective encoding must be Windows-1252. Other encodings are
conservatively omitted in this initial subset. A prior unsupported code page or
font charset also disables this property path for the rest of the parse. Properties must be immediate `sp` groups containing one `sn` followed by one
`sv`, with no nested content. Property order may vary. Strings accept printable
ASCII literal bytes, ASCII hex escapes, and escaped braces/backslashes. This is
an intentionally incomplete subset: Unicode control sequences, non-ASCII bytes,
line/paragraph controls, fields, binary data, and formatting inside properties
are rejected rather than partially emitted.

Only `shapeType`, `fGtext`, `fGtextOK`, `gtextUNICODE`, `gtextFont`, `gtextSize`,
`fHidden`, `fBackground`, and `fIsButton` are accepted property names. Every name
must occur at most once. Numeric values must be signed 32-bit decimal integers;
the type and enable flags use the exact canonical values above. The three
visibility/background/action flags must be absent or exactly `0`. Font text is
bounded to 128 characters and is not emitted; size is validated but not rendered.
Unknown properties, links, master/next identifiers, rich WordArt text, duplicate
properties, multiple instruction groups, and any competing `shptxt` (including
empty text) reject the property candidate. Only the four numeric rectangle
controls are accepted outside the instruction group. A legacy `shprslt` sibling
remains opaque in either order and supplies neither properties nor text.

Groups, nested shapes, shapes inside existing shape text, legacy drawing
containers, and hidden/deleted or skipped ancestors cannot enter this path.
Malformed candidates leave existing primary text behavior intact. There is no
cross-shape deduplication: two independent accepted shapes with identical text
produce two stories. Accepted text uses the existing textbox sink and projection,
including structured-story aggregation when another textbox contains a table.
Main tables and headers remain separate.

The observer has at most four grammar frames, a fixed property-name set, and a
65,536-character text cap further restricted by `max_text_chars`. It consumes the
existing lexer stream without rescanning source or storing fallback tokens.
An overflowing text value is discarded immediately and marked as overflowed;
the observer continues validating the remaining value syntax and properties. Only
a fully eligible candidate raises the property text limit error at shape close.
Disabled, hidden, unsupported or malformed candidates remain omitted, regardless
of whether their disqualifying property precedes or follows the oversized value.
No overflowed prefix is published. Unsupported syntax stops collection; depth
and lexical limits still apply while the normal parser skips it. Accepted text and subsequent story separators are
charged to the shared text budget before publication. Unicode-rich WordArt,
other shape types, and wider property grammars require further evidence and tests;
no complete WordArt or layout parity is claimed.

`break-controls.rtf` is a negative alternative probe: LibreOffice exports `AB`
and `CD` for the authored `zwbo`/`zwnbo` examples, matching the parser's paragraph
content. It does not supply independent positive evidence for another change.

## Reproduction and validation

From the repository root:

```sh
.venv/bin/python -m pytest tests/test_rtf_fallback_text.py tests/test_rtf_wordart.py -q --tb=short
RTF_FALLBACK_LO=1 .venv/bin/python -m pytest tests/test_rtf_fallback_text.py tests/test_rtf_wordart.py -q --tb=short
.venv/bin/ruff check src/legacy_office_parser/rtf.py tests/test_rtf_fallback_text.py tests/test_rtf_wordart.py
```

Live tests use the existing `tools/check_performance.py` conversion child with a
fresh isolated LibreOffice profile, a 45-second parent timeout, process-group
cleanup, and the helper's memory/CPU limits. LibreOffice is a test-only dependency;
the parser stays passive. The live suite requires `/usr/bin/libreoffice` and may
need permission to run outside a restrictive sandbox.

Completed local validation of this implementation:

- RTF modules plus `test_security_side_effects.py`: **339 passed, 16 skipped**.
- Both new test modules with `RTF_FALLBACK_LO=1`: **121 passed**, including all
  twelve original live conversion cases.
- Zeno's exact disabled `xxx` / `max_text_chars=2` reproducer, added after
  those suite runs: **1 passed** separately, preserving body `AB` and no textbox.
- Ruff on the changed parser and both new test modules: **passed**.

Independent review identified premature overflow errors for ineligible WordArt.
The fix and regression tests are awaiting re-review. These results do not claim validation on newer
LibreOffice versions or Microsoft Word. Suggested review focus: final-property
validation before publication, suppressed ancestry, rejected nested/group
ownership, effective-encoding uncertainty, and shared text/separator budgets.
