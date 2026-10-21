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
The original 0.17 subset accepted printable ASCII under Windows-1252. The 0.18
extension described below accepts flat Unicode and selected code-page text only
in `gtextUNICODE`. Property names, numeric values and the ignored font-name
property retain their strict ASCII grammar. A prior unsupported code page or
font charset disables the property path for the rest of the parse. Properties
must be immediate `sp` groups containing one `sn` followed by one `sv`, with no
nested content. Property order may vary. Line/paragraph controls, fields and
formatting are unsupported as property text; Unicode fallback tokens are counted
and skipped without executing their semantics.


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
charged to the shared text budget before publication. Other shape types, nested
property formatting and wider property grammars require further evidence and tests;
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

Historical 0.17 validation before the Unicode extension:

- RTF modules plus `test_security_side_effects.py`: **339 passed, 16 skipped**.
- Both new test modules with `RTF_FALLBACK_LO=1`: **121 passed**, including all
  twelve original live conversion cases.
- The independently reported disabled `xxx` / `max_text_chars=2` reproducer, added after
  those suite runs: **1 passed** separately, preserving body `AB` and no textbox.
- Ruff on the changed parser and both new test modules: **passed**.

Independent review identified premature overflow errors for ineligible WordArt.
The fix and regression tests passed independent re-review and were integrated in 0.17. These results do not claim validation on newer
LibreOffice versions or Microsoft Word. Suggested review focus: final-property
validation before publication, suppressed ancestry, rejected nested/group
ownership, effective-encoding uncertainty, and shared text/separator budgets.


## Unicode and code-page extension (0.18)

### Primary basis and accepted grammar

Microsoft's [RTF Unicode header rules](https://latex2rtf.sourceforge.net/rtfspec_6.html)
apply the Unicode mechanism to destination text. `ansicpg` identifies the ANSI
encoding; `u` carries a 16-bit unit with fallback governed by scoped `uc` (default
one). A control or binary token counts as one fallback character, and group
boundaries end fallback skipping. The Unicode Consortium's
[UTF-16 FAQ](https://www.unicode.org/faq/utf_bom.html) defines high/low surrogate
pairs for supplementary characters. These are primary format rules; no external
reader implementation was copied.

Only `gtextUNICODE` gains decoding. Its inherited effective encoding must be
Windows-1252, Windows-1251 or Windows-932 (Shift-JIS), selected by the existing
parser's document/font state. This allowlist is the tested subset, not a claim
that other encodings are invalid RTF. An inherited `uc` count is copied into the
property. Flat local `uc` and `u` controls are accepted, along with literal and
hex-escaped encoded bytes and escaped syntax characters. Signed units and the
existing decoder's unsigned 16-bit compatibility range are retained. A valid
surrogate pair produces one Unicode scalar value. The local fallback count and
pending decoder/surrogate state never escape the value.

Nested groups, `upr` alternatives, local code-page/font switches, rich text,
fields, C0/C1 controls, invalid encoded sequences and unpaired surrogates reject
the entire candidate with the existing omission warning. Replacement characters
are not invented to rescue a malformed property. The main document's existing
malformed-text recovery behavior is unchanged. A binary token is accepted only
as skipped Unicode fallback; its payload is still opaque and length-checked by
the shared lexer. No active destination is opened or executed.

### Decoder reuse, ownership and limits

`_PropertyText` supplies a bounded sink to the existing `_Parser.byte_text`,
`flush`, `emit`, `unicode` and `high_end` methods. It consumes `_tokens` records
from the same parse loop, with no second lexer, input scan, recursive document
parse or story dispatch. The sink rejects decoding warnings rather than retaining
replacement text. Incremental byte decoding crosses literal/hex token boundaries,
including DBCS lead/trail bytes. Its byte scratch is at most
`min(4096, max_text_chars)`; retained decoded text is at most
`min(65536, max_text_chars)` Unicode scalar values. On overflow it clears retained
text, continues validating and defers the error to complete shape eligibility.
An invalid tail or later disqualifying property cannot turn an overflowed prefix
into published text. Eligible overflow still raises `LimitExceededError`.

Strict standalone type-136 ownership, explicit enable flags, hidden/deleted
ancestry, duplicate/unknown property rejection, and the opaque `shprslt` boundary
remain unchanged. Accepted text and aggregate separators use the existing shared
text budget. No model, API, runtime I/O or converter dependency was added.

### Independently authored evidence

Nine original ASCII RTF files in `tests/fixtures/rtf_wordart_unicode/` were converted
with **LibreOffice 7.4.7.2 40(Build:2)** to temporary FODT. Their literal expected
shape paragraphs are:

- `unicode.rtf`: `Grüße Ж 😀` (BMP Unicode plus surrogate-pair emoji).
- `uc-zero.rtf`: `Ж😀`; `uc-two.rtf` and `inherited-uc.rtf`: `ЖX`.
- `cp1252.rtf`: `Café €`; `cp1251.rtf` and `font1251.rtf`: `Привет`.
- `cp932.rtf`: `日本`, with separately escaped DBCS bytes.
- `scoped.rtf`: two separate shapes, `Пр` then `Café`, after restoring the outer
  code page.

All nine live observations matched those literal expectations. Source hashes,
converter version and observed paragraphs are persisted in `lo-observations.json`.
Parser output was not used to generate fixtures or expected text. These files
contain no external references or active objects. They establish tested examples,
not complete rendering parity or validation of other LibreOffice versions.

Tests additionally cover fallback bytes/control/binary tokens, surrogate errors,
invalid code pages and encoded sequences, sibling state isolation, skipped
ancestors, continued validation after overflow, decoded-character limits,
separator costs and bounded scratch. Three formerly rejected values (`\u1040?`,
`\uc0\u65`, and byte `0x80`) now have positive literal assertions; rejection
coverage uses invalid units/counts and undefined byte `0x81` instead. The
independent public API/CLI regression is run unchanged.

```sh
.venv/bin/python -m pytest tests/test_rtf_wordart_unicode.py tests/test_rtf_wordart.py tests/test_rtf_wordart_api.py -q --tb=short
RTF_UNICODE_LO=1 .venv/bin/python -m pytest tests/test_rtf_wordart_unicode.py -q --tb=short
```

Completed 0.18 validation:

- All RTF test modules plus `test_security_side_effects.py`: **457 passed,
  25 skipped**, including the public API/CLI regression and 47
  independently authored review cases, both run unchanged.
- WordArt, fallback, Unicode and API modules with `RTF_UNICODE_LO=1` and
  `RTF_FALLBACK_LO=1`: **201 passed**, including all 21 original live conversions.
- Ruff on the changed runtime and authored test modules: **passed**.
- The corrected `rtf_wordart_unicode` resource child: **passed**. The
  700,138-byte input with 100,000 Unicode escapes uses `max_records=300000` and
  `max_text_chars=128`; it asserts the exact `RTF WordArt property text limit
  exceeded` error. Peak RSS in this run was **29,608 KiB**. An earlier checker
  used the default lexical budget and rejected before reaching property
  eligibility; that earlier run is not evidence for the property-overflow path.

Final independent review reported no actionable findings after rerunning the
457-test suite and the exact property-overflow resource check. No newer-LibreOffice or Microsoft
Word parity is claimed.
