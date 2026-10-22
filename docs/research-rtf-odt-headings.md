# RTF and ODT heading reference evidence

Original synthetic fixtures prepared on 2026-10-22 for the 0.22.0 heading work.
This is test-only evidence for the direct document model. It introduces no
production conversion path, dependency on Office at runtime, or parser edits.
All fixtures contain original synthetic content.

## Primary specifications

- Microsoft, **Rich Text Format Specification 1.9.1**, “Style Sheet” and
  “Paragraph Formatting Properties”: [official specification archive](https://officeprotocoldoc.z19.web.core.windows.net/files/Archive_References/%5BMSFT-RTF%5D.pdf),
  identified by Microsoft's [MS-OXRTFCP informative references](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfcp/85c0b884-a960-4d1a-874e-53eeee527ca6).
  Paragraph style selection uses `\sN`; `\sbasedonN` supplies style inheritance.
  `\outlinelevel0` through `\outlinelevel8` represent headings 1 through 9;
  the default is body. The specification entry does not explicitly enumerate
  operand 9: its use as an explicit body reset here is independently verified
  by the saved and live LibreOffice DOCX readbacks (both direct and style-local
  cases), not claimed as a quotation from that entry. `\pard` resets paragraph
  properties. Neither a style number nor its
  display name alone establishes an explicit outline level. The parser
  intentionally adds an exact “Heading N” compatibility fallback
  with an inference warning; that policy is separate from this wire evidence.
  The test deliberately uses
  arbitrary custom style IDs 10/11 and an ordinary style named “Heading 1”.
- OASIS, **OpenDocument 1.3 Part 3**, [official schema specification](https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html):
  sections 5.1.2 (`text:h`), 5.1.3 (`text:p`), the `text:outline-level` attribute,
  and `style:default-outline-level`. Heading semantics belong to `text:h`.
  The style default instructs an editor when assigning a paragraph style; it
  does not turn an existing `text:p` into a heading during reading. Plain
  paragraphs remain body even with a heading-named style or inherited default.
- Microsoft's [OOXML outlineLvl reference](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessingml.outlinelevel)
  describes explicit levels 0–8 and body value 9. The fixture-only DOCX probe
  reads paragraph properties first, then `w:basedOn` chains, without using
  style names. It checks both document paragraphs and header parts.

## Provenance and literal expectations

The existing `tests/fixtures/doc_headings/authored.docx` is the original,
deterministically generated synthetic source. It is reused without modification.
Its generator is `tests/fixtures/doc_headings/fixture.py`; the new tests do not
import that generator or any production decoder to determine expectations.

`tests/fixtures/paragraph_headings/reference.py` contains literal expectations:
Heading one = 1; Heading two = 2; Ordinary body = body; Inherited heading = 1;
Direct body override = body; Custom body style = body; Direct outline three = 3;
Cell heading = 2; Header heading = 2. Every label ends in “specimen”.

LibreOffice **7.4.7.2, 40(Build:2)** produced these saved artifacts:

- `authored.odt`: DOCX exported to ODT. All nine intended values survive.
- `readback/odt/authored.docx`: that ODT reopened and exported to DOCX. All nine
  values survive, independently confirmed by OOXML properties and inheritance.
- `authored.rtf`: DOCX exported to RTF. **All outline properties are absent**,
  including from its stylesheet. It still has style names Heading 1/Heading 2,
  IDs 1/2, and custom styles 20/21 based on 1. Its literal stored-outline and
  LibreOffice-readback expectation remains body for all nine. The parser applies
  the compatibility inference described below; it cannot recover the lost
  explicit properties from these labels.
- `readback/rtf/authored.docx`: the exported RTF reopened into DOCX. All nine
  values are body, matching the raw RTF evidence rather than the original intent.
- `explicit.rtf`: independently authored ASCII source, not a patched LO export.
  Its stylesheet explicitly supplies levels 0/1, a custom inherited style, and
  a custom body child. Paragraph controls supply body override 9 and direct
  heading 2 (public level 3). A table and header each select the level-2 style.
  An extra ordinary paragraph selects a style named “Heading 1” with no outline.
- `readback/explicit/explicit.docx`: LibreOffice readback of that original RTF
  preserves all ten literal expectations, including the misleading-name body.

The ODT evidence checks `content.xml` and `styles.xml` directly. Inherited heading
and direct body override select the same `Research_20_inherited` style, but are
stored as `text:h` and `text:p` respectively. The table heading is in its cell;
the header heading is in the master-page header. A separate in-memory ODT test
assigns `Heading_20_1` to an ordinary `text:p`, retaining body semantics.

The RTF evidence checks exact original control clauses and the exported style
IDs. This is deliberately a small ASCII fixture probe, not another general RTF
parser. The exported RTF repeats the header in an ignorable LibreOffice
`pgdsctbl` destination; public projection must still contain it exactly once.

## Independent oracle versus compatibility inference

The independent expectations in `reference.py` and `ORACLE_CASES` remain unchanged.
Saved and live DOCX probes use only those expectations. The exact “Heading N”
style-name fallback is a compatibility policy, not proof of
stored outline semantics or equivalence to LibreOffice. Separate literal
`PARSER_RTF_EXPORT` and `PARSER_EXPLICIT` expectations in the test file describe
that policy; no production decoder computes either expected mapping.

For `authored.rtf`, the parser infers Heading one = 1, Heading two = 2, Inherited
heading = 1, Direct body override = 1, Custom body style = 1, Cell heading = 2,
and Header heading = 2. Ordinary body and Direct outline three remain body.
The independent readback still expects all nine to be body. In particular,
LibreOffice export discarded the direct body override on style 20 and the
style-local body override on style 21: the remaining parent-style chain cannot
distinguish them from an intended inherited heading. Fallback therefore promotes
two originally body paragraphs. It also cannot recover the direct level-3 heading
on Normal. The inference is useful compatibility behavior but is lossy and does
not reconstruct the original DOCX semantics.

For `explicit.rtf`, only “Misleading style name specimen” differs: the independent
source/readback expectation is body, while compatibility inference yields level
1 from its exact “Heading 1” style name. All explicit and inherited outline
properties retain their original expectations. The label is retained to make
this deliberate inference difference visible, not to classify it as a defect.

Both RTF parser cases require exactly one document warning:
`RTF heading levels inferred from built-in style names.` The ODT case must not
emit this RTF warning. A separate assertion lists every difference between parser
and independent oracle mappings, so changes cannot silently blur the distinction.
Two deterministic temporary variants add `\outlinelevel9` either directly to
that paragraph or to its exact “Heading 1” style. Both must stay body: explicit
body evidence takes precedence over the name fallback. These variants test the
parser policy; they are not represented as additional saved LibreOffice oracles.

## Checks and converter-loss policy

Saved source/XML evidence and public-model checks run without LibreOffice.
Only the three live conversions require `OFFICE_CORPUS_LIBREOFFICE=1`.
They reopen each saved RTF/ODT into DOCX and assert the complete independent
literal mapping. There is no generic “missing headings allowed” rule, no filtering
to the subset that passed, and no xfail masking defects. The only recorded loss
is the specific original-DOCX-to-RTF export above, already reflected in that
fixture's independent expectation. Explicit RTF and ODT live checks allow no losses.

Public checks use the separate compatibility mappings and verify exact nonempty
paragraph membership, heading values, omitted JSON keys for body paragraphs,
table/header ownership, and one occurrence of each original label in the plain
text projection. Source probes and saved readbacks establish independent evidence
without adopting the parser's fallback policy.

The default run reported **14 passed, 3 skipped**; Ruff passed. All three opt-in
live readbacks passed. Independent outline expectations and parser compatibility
expectations remain separate.

## Reproduction with bounded conversions

Run from the repository root. The source and destination arguments below are
absolute, destination directories must already exist, and each invocation gets
an isolated disposable LibreOffice profile. The wrapper enforces 1024 MiB address
space and 60 CPU seconds; `bounded` enforces 90 wall seconds and kills/reaps the
private process group. Keep these bounds when running reference conversions.

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'tools')
from check_performance import bounded
repo = Path.cwd().resolve()
fixtures = repo / 'tests/fixtures/paragraph_headings'
source = repo / 'tests/fixtures/doc_headings/authored.docx'
jobs = []
for fmt in ('rtf', 'odt'):
    jobs.append((source, fixtures, fmt))
    jobs.append((fixtures / ('authored.' + fmt), fixtures / 'readback' / fmt,
                 'docx:Office Open XML Text'))
jobs.append((fixtures / 'explicit.rtf', fixtures / 'readback/explicit',
             'docx:Office Open XML Text'))
for src, dest, fmt in jobs:
    dest.mkdir(parents=True, exist_ok=True)
    result = bounded([sys.executable, str(repo / 'tools/check_performance.py'),
                      '--convert-child', '/usr/bin/libreoffice', str(src),
                      str(dest), fmt], 90)
    assert result['status'] == 'ok', result
    assert (dest / (src.stem + '.' + fmt.split(':')[0])).is_file()
PY
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_heading_reference.py
OFFICE_CORPUS_LIBREOFFICE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/test_heading_reference.py -k live
```

The text source `explicit.rtf` is deterministic. Converted ZIPs and RTF metadata
are reader-produced artifacts, not guaranteed byte-identical across versions.
A new export must be reinspected before changing any literal expectation.
The manifest records the saved artifact hashes and the reused source hash.
Fixtures do not establish Word compatibility, malformed-input handling, every
story type, arbitrary style cycles, or resource-limit behavior of the parser.
