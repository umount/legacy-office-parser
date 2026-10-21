# Standalone legacy RTF textbox extraction

Explicit standalone drawing text uses the existing bounded RTF story reader.

## Primary evidence

Microsoft's RTF specification, reproduced in the
[Drawing Objects section](https://latex2rtf.sourceforge.net/rtfspec_7.html),
defines the legacy drawing destination as `{\*\do ...}`. Its textbox primitive
uses `\dptxbx`, followed by optional flow controls, a margin, and an explicit
`{\dptxbxtext <para>+}` destination. Legacy groups contain drawing primitives;
callouts include a textbox primitive. This provides the text-only entry point.
No reader implementation or third-party fixture was copied.

The same specification describes `shprslt` as the older representation of a
modern shape. Linked boxes may lack a local primary story, and a group fallback
represents the entire group. Those facts do not establish a general fallback
selection algorithm. This implementation does not attempt one.

## Extraction contract

Group-scoped drawing ancestry is tracked separately from text suppression.
A `legacy_container` flag permits traversal of standalone `do` containers without emitting their literal text or executing their paragraph/table
controls. Only an explicit `dptxbxtext` destination inside that context opens a
textbox sink. Group and callout geometry is neither interpreted nor required to
construct text. Drawing primitive counts and geometric validity are not validated.
An orphan `dptxbxtext` destination is skipped.

The existing text path handles charset/font selection, Unicode fallback and
surrogates, fields, text-run visibility, paragraphs and tables. Inherited hidden
and deleted state is preserved on entry. Explicit text controls can reset that
state. Structured table-bearing stories and their string projections follow the
existing `story_blocks` contract; independent identical stories remain distinct.
Body and header sinks are not modified by drawing container controls.

`shprslt` remains a hard skip, in either position relative to primary shape text.
A `do` encountered anywhere under modern shape ancestry, including within
visible `shptxt`, is also skipped. Recognized modern shape/text destinations under legacy ancestry do not open
extra stories. Header/footnote and font-table destinations under either drawing
ancestry are blocked before their handlers run, including in visible textbox
text. `nesttableprops` is blocked in suppressed drawing containers but remains
available in actual textbox text at a valid nested-table depth. No skipped ancestor can be reopened. Property groups,
unknown optional destinations, pictures, objects and background drawings retain
the existing skip behavior. Binary tokens remain opaque and length-checked.

Text, cell, lexical record and depth budgets continue through the existing
reader paths, including separators and retained structured-story projections.
There is no new I/O, runtime converter, fallback buffer or rendering dependency.

## Independent verification

All expected results are literal, authored assertions. The new test module
constructs its own standalone, grouped and callout RTF primitives without parser
helpers. It checks duplicate independent stories, charset/Unicode/field text,
hidden/deleted inheritance and reset, skipped ancestors, unchanged modern
fallback behavior, property/container/binary decoys, body/header isolation,
structured table stories, surrogate boundaries, malformed operands, and limits.

Regression commands:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rtf*.py tests/test_security_side_effects.py
.venv/bin/ruff check --no-cache src/legacy_office_parser/rtf.py tests/test_rtf_legacy_textboxes.py
RTF_LEGACY_LO=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rtf_legacy_textboxes.py -k libreoffice
```

Initial checkpoint: **206 passed, 4 skipped** for the RTF/side-effect suite; Ruff passed.
The new module has 34 ordinary cases and one optional converter case. Positive cases cover standalone/group/callout text, independent identical
stories and encoded text.

The optional test writes an original RTF fixture into pytest's temporary
directory, converts it using an isolated LibreOffice profile, and inspects only
`draw:text-box` paragraphs in FODT. The independently authored expectation is
exactly `Legacy`, `Second`; the parser must retain `Legacy\nSecond`.
LibreOffice **7.4.7.2 40(Build:2)** passed this comparison. 
No private documents, persistent fixture binaries or external corpus were used.

## Remaining scope

This closes standalone legacy explicit textbox text extraction, not general
shape fallback recovery. `shprslt`, linked-box layout, drawing geometry, z-order,
WordArt/property strings and arbitrary producer variants remain unsupported.
The LO comparison covers the authored standalone fixture only; group and callout
cases have independent syntax tests but are not claimed as converter parity.
Visibility means supported text-run controls, not full rendered visibility:
shape properties such as `fHidden`, clipping and occlusion are not evaluated.

## Drawing scope and validation

The reader keeps `shape_ancestor` and `legacy_ancestor` throughout visible
textbox descendants. Group restoration restores these flags; opening text
clears only container suppression. Drawing metadata cannot redefine document
fonts or open secondary header, footer or note stories. Container-only table
controls are inert, while valid nested tables inside textbox text remain active.
`shprslt` remains a hard skip.

Regressions cover metadata scope, nested-table controls, alternate drawing
representations and restoration after closing groups. The focused RTF and
side-effect suite has **230 passed, 4 skipped**. The new module has 56 ordinary
cases and one LibreOffice case; running it with `RTF_LEGACY_LO=1` gives
**57 passed**. Ruff passes.
