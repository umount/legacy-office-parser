# Explicit WordArt text in Windows-1250 and Windows-1253

## Decision and primary basis

This change extends the existing explicit WordArt text path by two encodings.
It does not recover legacy shape fallbacks. The ownership limits described in
[the fallback investigation](research-rtf-fallback-text.md) and
[legacy textbox research](research-rtf-legacy-textboxes.md) remain applicable.

Microsoft's RTF specification, reproduced in its
[drawing-object section](https://latex2rtf.sourceforge.net/rtfspec_7.html), defines
`gtextUNICODE` as a Unicode string and requires enabled WordArt properties for
its interpretation. The same section says linked textboxes can lack local
`shptxt`, and a group's legacy result represents the group. Those rules do not
justify promoting fallback text merely because primary text is absent.

The specification's [header and Unicode rules](https://latex2rtf.sourceforge.net/rtfspec_6.html)
list code pages 1250 and 1253, font charsets 238 and 161, document `ansicpg`, and
font-specific `cpg`. Unicode escapes and scoped fallback counts apply to
destination text. Microsoft's [Code Page Identifiers](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers)
identifies Windows-1250 as Central European and Windows-1253 as Greek. These are
encoding declarations, not font substitution or language-detection heuristics.

## Concrete omission and implementation

Before this change, the strict WordArt observer was created only when the
existing parser resolved the effective encoding to CP1252, CP1251, or CP932.
Therefore an otherwise eligible explicit shape containing CP1250 `Žluť` or
CP1253 `Ελλάδα` was omitted. Even a Unicode-only `\u937?` string was omitted under
CP1253, before the decoder had a chance to read it.

The runtime change adds `cp1250` and `cp1253` to that single allowlist. It reuses
existing document/font encoding selection and the bounded `_PropertyText`
decoder. Literal bytes, hex escapes, Unicode units, surrogate handling, and
fallback tokens follow the existing grammar. Local font/codepage changes inside
a property remain unsupported. Property names and numeric metadata remain ASCII.
No character-control or rich-text grammar extension is included.

Shape ownership is unchanged: standalone type 136, explicit enable flags,
unique recognized properties, no competing primary text, no linked/grouped or
hidden/deleted ancestry, and no reopening of suppressed destinations. A prior
unknown codepage or unsupported font charset still blocks this observer. Invalid
encoded bytes reject the whole candidate without replacement or partial text.
An undefined byte used only as skipped Unicode fallback is not decoded.

No additional buffers, decoder passes, recursive parsing, I/O, or dependencies
are introduced. Existing text, stream, lexical-record, depth, and projection
budgets apply. Eligible overflow still raises at final shape validation;
ineligible or malformed candidates never publish an overflowed prefix.
Independent identical shapes remain independent textbox stories.

## Original tests and independent conversion

`tests/test_rtf_wordart_codepages.py` authors source bytes and expected Unicode
strings literally. No private inputs, copied reader implementations, generated
expected text, or persistent binary fixtures are used. The inputs cover:

- Document CP1250 bytes and Unicode escapes yielding `Žluť`.
- Document CP1253 bytes yielding `Ελλάδα`, and Unicode-only `Ω`.
- Font charset 238/161 and explicit font `cpg1250`/`cpg1253` selection.
- Mixed literal/hex bytes, group restoration, font precedence, and sibling state.
- Invalid bytes, malformed surrogates, rejected rich/local controls, uncertain
  encodings, direct and inherited visibility, links, duplicate properties,
  primary/fallback separation, and budgets.

The live test writes eight original RTF inputs to temporary directories, converts
them to temporary flat ODF with the existing bounded helper and an isolated
LibreOffice profile, and compares only shape paragraph text with literal
expectations. Source bytes must remain unchanged. No image generation or visual
rendering is used. The parser comparison is separate from the independent
converted-text assertion. This is finite converter evidence, not a claim of
complete Microsoft Word or newer-LibreOffice parity.

Font fixtures declare the default font before the font table and explicitly
select it before body text. An initial exploratory header with late `deff` and
no explicit selection produced different Writer text; it is not used as positive
evidence. The final tests follow the primary header ordering.

One old negative test previously used CP1253 as a deliberately unaccepted
encoding. It now uses CP1254, preserving that negative assertion's purpose.
No other prior expectations are weakened.

## Reproduction

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rtf_wordart_codepages.py
RTF_WORDART_CODEPAGES_LO=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rtf_wordart_codepages.py -k live_independent
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rtf*.py tests/test_security_side_effects.py
.venv/bin/ruff check --no-cache src/legacy_office_parser/rtf.py tests/test_rtf_wordart_codepages.py tests/test_rtf_wordart_unicode.py
```

General fallback-only recovery, other untested encodings, local encoding changes
inside WordArt properties, richer property grammar, rendering visibility and
linked/group ownership remain outside this extension.

Completed validation: **769 passed, 33 skipped** for all RTF modules and the
side-effect suite; **8 passed** for the independent live code-page examples with
LibreOffice 7.4.7.2; Ruff passed on the runtime and both affected test modules.
