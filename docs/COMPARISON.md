# Extraction quality and alternatives

## What we have achieved

`legacy-office-parser` provides one Python API for faithful text and structured
data from DOC, XLS, PPT, RTF, ODT, ODS and ODP. It extracts directly from the
source formats, without running LibreOffice, Java, macros, scripts or formulas,
and without fetching external resources. Its sole runtime dependency is `olefile`.

**On the verified extraction cases, the parser matches the content and structure
checked against LibreOffice; in specific documented cases, it preserves source
structure or repeated content that LibreOffice conversion loses.** This claim
applies to the tested properties and fixtures, not every feature of every file.

The reference application actually used is **LibreOffice**, including local
7.4.7.2 checks and the version installed by the Ubuntu 24.04 CI job. Apache
OpenOffice has not been tested separately. Neither exact rendering nor complete
compatibility with either office suite is claimed.

## Why we built a focused package

The initial review identified gaps between the available extraction approaches
and our requirements: source reading order, nested tables, stable cell positions,
current presentation state, linked notes and a consistent typed result. These
were implementation-specific findings, not a benchmark establishing that every
alternative library is worse than LibreOffice or this package. The recorded
versions and scope of the review matter.

- **sharepoint-to-text**, revision `6f2e77ca4b5fcf4e42550b9d1bb3cd51a4078dec`:
  the inspected DOC path guessed text location/encoding and inferred tables
  from flat text, rather than reading CLX piece tables. Targeted probes exposed
  Cyrillic misclassification and false table detection. Its inspected PPT path
  scanned records without resolving the current persist directory; probes
  exposed empty-slide, note-association and shape-text cases. We instead read
  explicit DOC structures and resolve active PPT records and relationships.
  A full end-to-end benchmark of that package was not performed.
- **WordCraft**, revision `e05b7fe86f3b85454000dffc321de638d7009817`:
  its DOC reader was a useful structural reference, but the inspected table
  representation flattened levels deeper than one. Our model preserves nested
  tables in `Cell.blocks`, including auxiliary stories. Targeted source/module
  checks also motivated tests for compressed DOC character mappings and UTF-16
  surrogate pairs split across pieces. The full WordCraft application was not
  benchmarked on the private corpus. These findings do not describe every later
  revision of that project.
- **office_oxide**: inspected as a Rust/Python alternative with real DOC piece
  tables and PPT persist-directory handling. The reviewed source flattened
  nested DOC tables; PPT note completeness and some fallback paths required
  further verification. This was source research, not a result for every
  published Python wheel or a current-version performance comparison.
- **Apache POI HWPF/HSLF**: an additional algorithmic reference for DOC/PPT.
  We did not adopt its Java runtime. No measured overall quality ranking against
  POI is claimed.
- **xlrd 2.0.2, striprtf v0.0.29 and odfpy**: useful format-specific references,
  not evidence of a general quality deficit. We chose one shared API, model and
  limit policy across seven formats rather than adding separate runtime readers.
  The package does not claim to outperform all of their supported features.

The underlying investigations and upstream links are in [RESEARCH.md](RESEARCH.md),
[XLS research](research-xls.md), [RTF research](research-rtf.md) and
[OpenDocument research](research-odf.md). Attribution is recorded in
[THIRD_PARTY.md](../THIRD_PARTY.md).

## Version 0.17 follow-up

Version 0.17 added DOC comments with authors and source ownership,
empty XLS display sections without losing typed values, and a conservative
literal RTF WordArt subset. The combined local suite passed 3,804 tests (51
optional skips), 9,500 mutations and 11 resource checks. New original fixtures
were also checked with LibreOffice; see [validation details](TESTING.md).
The WordArt overflow correction passed independent re-review, and
[CI passed](https://github.com/umount/legacy-office-parser/actions/runs/39678107409)
on Python 3.11–3.13 and the LibreOffice reference job.
These additions extend measured coverage, not the claim to arbitrary documents.

## Recorded 0.16 evidence behind the extraction claim

For version 0.16, the full local suite passed **3,507 tests**, with **37 optional
tests skipped** in the ordinary run. The DOC-note and PPT-comment suites passed **111 tests** with live reference
checks enabled; two of those tests invoke LibreOffice directly. CI for commit `c18086c` passed on Python 3.11, 3.12
and 3.13, including the separate LibreOffice reference job:
[verified CI run](https://github.com/umount/legacy-office-parser/actions/runs/39673819350).

The checks use independently authored expected content, structural assertions
and reference readers. They cover reading order, nested tables, cell positions
and merges, auxiliary stories, note ownership, current slides and associated
notes/comments, typed spreadsheet values and supported display formats. The
scope differs by fixture and oracle; a successful conversion or matching word
count is not treated as proof of complete structure.

Specific recorded outcomes include:

- Five private DOC documents matched LibreOffice's total of **48 tables** in the
  recorded corpus comparison. Early word-set metrics were 99.921–100.000%; these
  are diagnostic metrics, not proof of exact equivalence. Later targeted fixes
  and the 0.16 regression retained the corpus's character and table counts.
  Private contents and document paths are not published.
- Four local XLS files matched **41,303 populated cells** by coordinates, types
  and values, as well as sheet order and merge ranges, in the recorded 0.3 check.
  This does not establish display-format or formula-cache freshness parity.
- The authored ODT notes fixture matches ordinary note content exactly. In the
  repeated-content fixture, LibreOffice 7.4.7.2 drops a repeated row; our parser
  retains both rows and their notes according to the authored expectations.
  See the [fixture evidence](../tests/fixtures/odf_notes/README.md).
- In the authored DOC-note case, newer LibreOffice preserves a binary table but
  exports it to DOCX as a textbox. Our model keeps the table. The reference test
  verifies that specific transformation from raw markers, the authored grid and
  the same note's selected XML representation; it does not flatten all tables
  to make comparisons pass. See [DOC note research](research-doc-notes.md).
- Supported DOC table-style visibility follows the recorded specification-based
  expectations where the local LibreOffice importer behaves differently.
  This is an explicit interoperability discrepancy, not independently established
  rendering superiority. See [table-style evidence](research-doc-table-styles.md)
  and [conditional-style evidence](research-doc-conditional-styles.md).

The final 0.16 validation also ran **8,100 deterministic mutations** without
unexpected exceptions and **11 resource checks**, plus installed-wheel checks for
all seven formats. These support robustness of the tested paths; they are not
proof of universal safety or semantic completeness. Details and historical
measurements are in [TESTING.md](TESTING.md).

## What “matches LibreOffice” does not mean

We do not claim full office-suite compatibility, universal lossless extraction,
identical layout, or a current end-to-end ranking against all libraries above.
Some constructs still require research or additional decoding. These include
remaining DOC table-style and ownership cases, general XLS formatting, ambiguous
RTF shape alternatives, and passive embedded or extension content in PPT/ODF.
The current scope is tracked in [EXTRACTION_GAPS.md](EXTRACTION_GAPS.md).

For LLM input, the achieved result is direct, structured extraction with explicit
limits and independently tested behavior, without a full office-suite runtime.
Performance measurements are kept separate in [PERFORMANCE.md](PERFORMANCE.md);
converter startup time is not presented as a pure parser-speed comparison.

## Version 0.18 Unicode evidence

Nine authored RTF WordArt fixtures match LibreOffice 7.4.7.2 for BMP characters,
surrogate-pair emoji, fallback counts, Windows-1252/1251/932 and restored encoding
scope. This extends the narrow explicit WordArt subset; it does not establish
support for arbitrary drawing properties or fallback-only shapes. The full local
suite passed 3,921 tests, 6,900 mutation samples and 12 resource checks.

## Version 0.19 text and selection evidence

Twelve preserved-XLS cells match LibreOffice CSV output for ordinary text
prefixes/suffixes and numeric controls. Two original DOC selections match source
XML, raw UTF-16 bookmark intervals and LibreOffice readback, including an empty
middle paragraph and astral characters. Raw XLS values and DOC reference anchors
remain available separately from display text and selected ranges.
The full local suite passed 4,172 tests, 7,100 mutations and 12 resource checks;
these findings extend measured coverage without implying arbitrary-file parity.
