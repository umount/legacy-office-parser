# Testing

For current 0.22 coverage and limitations, see [Extraction gaps](EXTRACTION_GAPS.md).
For achievements and comparisons with other libraries and LibreOffice, see
[Comparison](COMPARISON.md). Version-specific results below are historical snapshots.

## Quick checks

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check src tests tools
python -m build
```

CI tests Python 3.11–3.13. LibreOffice is not required at runtime or for regular
tests: generated binary fixtures are stored alongside their expected results.

## Private corpus

Place personal files in `tmp/`, whose entire contents are excluded from Git.
Do not publish extracted text, document snapshots, OOXML conversions, or diffs.

```sh
PYTHONPATH=src python tools/check_corpus.py tmp --libreoffice > tmp/corpus-report.json
```

The tool runs each parser separately, uses a temporary LibreOffice profile, and
deletes temporary documents. The report contains a hash identifier, sizes,
elapsed time, process max RSS, table/slide/sheet/cell counts, and word statistics.
LibreOffice timing includes process startup and conversion; this is not a direct
comparison of parser speed. RSS covers the entire Python process, not just the
parser. Matching word sets do not prove correct order, merges, or notes.
Synthetic fixtures with exact expectations test those properties.
DOC/RTF/ODT comparisons cover main text and textboxes; formatting fragments are
joined within paragraphs, and one branch is selected from AlternateContent.
This metric does not check PPT/ODP notes, footnotes, or ordinary header/footer text.
For XLS/ODS, the report compares sheet order, coordinates, types, stored values,
and merges. Empty cells containing only formatting are excluded on both sides;
`cells` and `populated_cells` may therefore differ.
The comparison does not reproduce number display or establish whether formula
caches are current. Ambiguous formats, recalculation, and conversion rounding are
reported separately rather than treated as equivalent. The tool accepts a
directory or a single file.

For DOC/RTF/ODT, additional checks cover main-text order, tables, coordinates,
spans, covered cells, and separate note stories. Only whitespace is normalized.
Unsupported scopes yield `equal: null`, not a successful check. Headers/footers
and textboxes receive pooled recoverable-text comparisons. Unresolved ordering,
structure or ownership remains incomplete or unknown, rather than equivalent.
For PPT/ODP, each slide's text, notes, and visibility are checked; order comes
from presentation.xml relationships, not ZIP member names.

```sh
python tools/check_corpus.py tests/fixtures --libreoffice --fail-on-difference
RTF_FIDELITY_LO=1 ODF_NOTES_LIBREOFFICE=1 python -m pytest -q tests/test_rtf_fidelity.py tests/test_odf_notes.py
```

`--fail-on-difference` returns a nonzero exit code when checked properties differ
or a comparison cannot be resolved. This is a diagnostic gate, not proof that
untested constructs are free of defects. Normal mode retains the difference
report, but its error exit code reflects parsing/conversion failures.
A separate CI job installs LibreOffice solely as a development reference.

## Required scenarios

- DOC: Cyrillic, UTF-16 and compressed pieces, multiple pieces in a different
  physical order; actual table properties, empty/multiparagraph cells,
  horizontal and vertical merges, supported nested tables, malformed nesting
  and depth-limit checks;
  separate text stories.
- PPT: empty slides do not shift numbering; notes are linked by identifier;
  shape text is retained when outline text is present; the current save chain
  is used, without old/deleted text.
- XLS: SST/CONTINUE and encoding changes within a string; RK/MULRK, cell types,
  formula results, 1900/1904 dates, errors/empty values, coordinates, and merges.
- RTF: groups and destinations, code pages, Unicode/fallback, binary blocks,
  fields, separate text stories, table rows and cells.
- ODF: ZIP/MIME/XML, repeated empty and populated rows/cells,
  stored fields/formulas, value types, merges, slides, and notes.
- Corruption: invalid offsets/lengths, reference cycles, truncated containers,
  encryption, and record/text/table/slide budgets.
- Distribution: the wheel installs and imports outside the source tree.

## Recorded results

Version 0.2 was tested on 2026-10-21 with Python 3.11 and 3.12: 428 tests, including
exact comparisons of synthetic documents in all seven formats and CLI checks;
Ruff reported no issues. Python 3.13 testing is configured in CI but was not run locally.
The wheel and sdist build successfully; the wheel was installed in a separate
clean environment, and the API for all seven formats was checked outside the
source tree. The CLI uses the same entry points. License notices are included
in the wheel; the project's own corpus and documentation are included in the sdist.

Five documents from the private DOC corpus parsed without errors. Table counts
matched LibreOffice in all five files (48 in total). Word-set recall against the
DOCX conversion was 99.921–100.000%, and precision was 99.921–100.000%.
These are diagnostic metrics, not confirmation of identical content.
Another 15 existing local samples were checked: 4 DOC, 5 XLS, 2 RTF, 2 ODT,
1 PPT, and 1 ODP. All parsed without exceptions. For RTF/ODT/PPT/ODP, word sets
matched the LibreOffice conversion by 100%. For five XLS files, sheet and
populated-cell counts matched, including a file with 40 007 cells.
One additional DOC had different word boundaries: the original 3×2 table was
extracted structurally, but LibreOffice's DOCX conversion concatenated its cells
and contained no table. All 222 non-whitespace characters matched in their
original order. Word-set recall of 96.67% and precision of 82.86% in this case
do not indicate text loss. The report retains these metrics and a separate check
of the non-whitespace sequence rather than concealing the structural difference.
External samples are not included in the public repository.

## Coverage snapshot for 0.12 (historical)

- Pre-Word 97 DOC, encrypted documents, and documents without CLX are unsupported.
  Explicit identity properties separate adjacent DOC tables.
  Nested DOC tables are retained in `Cell.blocks`, including tables in auxiliary
  stories under `Document.story_blocks`. Merges and grids are handled separately
  at each level. PTableProps/HugePapx, cell insertion/deletion, widths, and
  sequential merges are supported. Conditional table styles, preferred widths,
  and automatic layout are not evaluated.
- DOC respects inherited style visibility and direct hidden/deleted properties;
  fields use their stored results. Comments are omitted.
  Note anchors, header/footer variants, and textbox placement are not modeled.
  Active PLC ranges are used for textboxes; when the PLC is absent, all text is
  retained with a warning that the ranges have not been verified.
- PPT extracts active slides, linked notes, and WordArt from active shapes.
  Ordinary text from active masters is extracted; master placeholder fields,
  text in embedded objects, and rare extensions, including Metro blobs,
  are outside guaranteed coverage. A broader real-world corpus is needed.
- XLS: BIFF8 is supported; earlier BIFF versions are not. Formulas are not
  evaluated, and tokens are not translated into expressions; stored results
  may be stale. General, simple percentages, fixed precision, digit grouping,
  and scientific notation are supported, with the original number retained
  separately from display text. Explicit literals and ordinary sign sections
  are preserved; localized currency formats, negative conditional values,
  ambiguous conditions/thresholds, empty sections, scaling formats, and other
  unsupported formats retain the numeric value with a warning, as do ambiguous
  dates. Charts, macros, and drawings are omitted.
- RTF: tables in auxiliary stories retain their structure in `story_blocks`.
  Nested tables, ordinary rectangular merges, and `shptxt` text are supported.
  Ambiguous/irregular merges are simplified with a warning. Legacy fallback-only
  shapes, rare destinations, and HTML attachments are outside full coverage.
- ODT: tables in auxiliary stories are retained in `story_blocks`.
  Nested tables, ordinary notes, textboxes, and headers/footers from selected
  page templates are supported. Implicit pagination and visual order are not
  reproduced; embedded objects, some extensions, and nested/invalid notes are
  unsupported. Repeated ODS formulas retain their original expression without
  recalculating references.
- Images, OCR, and macro execution are not supported.

Always inspect `warnings`. The historical results below describe their respective
versions, not all current limitations. A broader corpus and investigation of
differences are needed before claiming complete format support.


## Additional checks for version 0.3

- Four local XLS files: 41 303 populated cells matched by coordinate, type, and
  value, as did sheet order and merges. The comparison uses the model's numeric
  domain, not the decimal number's string representation.
- In a project-authored XLS, LibreOffice replaces two BOOLERR values with `TRUE()`/
  `FALSE()`. Values match, but formula provenance differs; the report retains
  `conversion_boolean_formula` rather than declaring full equality.
- Project-authored ODT files with notes: the ordinary document matched in main
  text, footnotes, and endnotes. LibreOffice 7.4.7.2 loses a row in the repeated-row
  example; the parser preserves the repeated content. Sources, expectations, and
  recorded behavior are in `tests/fixtures/odf_notes/`.
- RTF: ordinary merges and shape text were checked using independently authored
  examples through LibreOffice. Text in horizontal continuation cells is retained,
  and a shape's fallback does not duplicate its primary representation.
- PPT: slide reordering and a hidden slide were additionally checked in a
  project-authored presentation. Text, notes, order, and visibility matched the conversion.
- Independent review of ODT notes and RTF merges/shapes found no confirmed defects;
  another 36 synthetic combinations of repetition, merges, and limits were checked.
  This is a bounded check, not proof of complete format coverage.


Corrupted variants of project-authored fixtures are checked using a reproducible sample:

```sh
timeout 120s python tools/check_mutations.py --seed 143 --cases-per-format 500
```

After the ZIP boundary fix, 3 500 cases completed without unexpected exceptions.
The script does not check the correctness of text from a corrupted document;
it checks that parsing returns a result or a classified `ParseError`. Unexpected
inputs are saved in the ignored `tmp/mutation-regressions/` directory for minimization.
This is a bounded sample, not an exhaustive robustness check.


The causes of the remaining differences in five personal DOC files were examined
separately. After the `CSymbol` fix, two PUA codes matched LibreOffice, and the
target document matched when whitespace was ignored. In the other four documents,
the identified numeric differences came from LibreOffice recalculating `REF`/`PAGE`
fields; the parser retains the stored field result without evaluating it.
No ordinary words were lost in this check. It does not replace testing all
stories and properties.


ODT textboxes are extracted separately from main text and cells. Headers/footers
are extracted from selected page templates; styles account for inheritance and
explicit/stored page breaks. Unused templates and hidden sections are excluded.
Main-story textboxes and notes precede the corresponding header/footer stories.
An independent fixture matched LibreOffice; detailed semantics and template
selection limits are documented in `tests/fixtures/odf_stories/README.md`.
Automatic pagination is not calculated: an implicit transition to the next template
may be omitted with a warning. Header/footer variants are combined without links
to specific pages. Masters remain outside coverage for ODS/ODP.

The final local 0.3 run comprised 736 regular tests and 12 opt-in checks;
a separate LibreOffice run executes 136 tests, including all opt-in checks.
CI runs regular checks on Python 3.11–3.13; a separate LibreOffice job checks
nine project-authored documents covering all seven formats, notes, textboxes, and RTF.
The BOOLERR conversion exception in CI is limited to two known coordinates in
one project-authored XLS and does not apply to arbitrary corpora.


## Checks for 0.4

Regular suite: 877 passed, 14 opt-in skipped. Separate LibreOffice run:
235 passed. Nested ODT matched an independent DOCX conversion, including three
tables and four cells. RTF is checked both on project-authored input and on
LibreOffice exports. DOC styles are checked in an original document with
inherited visibility and explicit overrides; WordArt is checked in an original PPT.

`Cell.blocks` preserves the order of nested paragraphs/tables; an empty field is
omitted from `Document.to_dict()` for compatibility with simple cells. `Cell.text`
contains the complete cell text. The text limit counts both projections and
retained child text; the cell limit covers every level. Repeated cells have
independent trees.

Resource-limit checks (Linux):

```sh
python tools/check_security_resources.py
python -m pytest -q tests/test_security_side_effects.py
```

Each resource scenario runs in a separate process: 256 MiB of address space,
8 seconds of CPU time, and 15 seconds of wall time. Small synthetic inputs test
decompression limits, XML/RTF depth, DTD rejection, OLE cycles, and ODF repetition.
Retained Python allocations are also measured after 140 parses with warm-up and
garbage collection; the growth threshold is 1 MiB. This is a short regression
check, not proof that there are no leaks. RSS reports the process peak and does
not replace retained-memory measurements.

Behavioral tests install an audit hook after warming up the parsers: input bytes
with external links, fields, scripts, and objects must not open files, access the
network, start processes, or modify the filesystem. The checks do not execute
embedded code or pass these documents to an office runtime. Quality comparisons
through LibreOffice use only separate, benign, originally authored fixtures.

An up-to-date Python with updated Expat/zlib and olefile is required. Parser
limits do not replace operating-system memory/CPU limits in the calling process.


### Checks for 0.4.1

ODF cell text is checked as paragraphs accumulate, before joining the string;
ODS/ODP visibility-style traversal respects `max_depth`. Regressions check the
point of failure, all three ODF formats, and unchanged normal behavior for short
chains. The resource suite includes 11 scenarios and reports Python, Expat, and
zlib versions. External-action checks include table sources, stored formulas,
and links with variable substitution. Locally: 891 passed, 14 opt-in skipped;
108 LibreOffice comparison tests pass for the affected paths.


## Checks for version 0.5

Nested DOC tables are checked against independent synthetic expectations and a
project-authored three-level DOC exported by LibreOffice from a minimal DOCX.
The comparison confirms four tables, eight cells, and text order. Tables in
auxiliary stories have separate regressions for projection, structure, and limits.
Methodology: `research-doc-nested.md`.

Headers/footers and textboxes are checked by recoverable text. For multiple
stories whose order is not preserved by the public model, the report leaves
equality unknown: matching word sets are not considered proof. Geometry and
anchors are not compared. Three live LibreOffice checks test a simple RTF
header/footer and its DOC/ODT conversions. If a LibreOffice version creates
multiple header/footer variants, each variant's content is checked while their
overall order remains unknown. If DOCX conversion combines identical variants
from DOC, the report retains the difference in copy counts; matching text in
each variant does not turn that difference into full equality. Tables and
textboxes are also covered by synthetic DOCX XML; this helper tool does not
yet compare `story_blocks` structure.

`check_performance.py` measures large ordinary documents in all seven formats;
size, reproducibility, measurement scope, and results are in `PERFORMANCE.md`.
After the PPT fix, all seven formats passed strict measurement without warnings
(three repetitions each). In 0.6, DOC diagnostics became more precise: the large
DOC retains its content but receives a warning about preferred widths. The
current strict DOC measurement therefore reports `validation_failed`; details
are in `PERFORMANCE.md`. Unknown PPT extensions are still reported.

A repeated local run of five personal DOC files parsed all of them, but every
comparison remained incomplete; three had differing non-whitespace sequences.
This is not proof of equivalence. Personal content and the reports themselves
are not included in the repository. New public fixtures contain only original
minimal examples.

DOC section breaks are checked using PLCSED: separate regressions distinguish
section breaks from manual page breaks, check CP boundaries, and verify table
preservation. A project-authored minimal DOC with two paragraphs and a table
parses without warnings. Specification and examples: `research-doc-sections.md`.

### PPT extension classification checks

After `ffe781c`: **1044 passed, 17 skipped**, Ruff reported no issues; 3500
deterministic mutations (seed 143) produced no unexpected exceptions. Added
47 regressions covering known metadata, unknown and textual content, invalid
headers/lengths, context, record and depth limits, and inactive objects.
Skipped tests require explicit opt-in to the external LibreOffice reference.

Research on external DOC properties: `research-doc-external-tables.md`; implementation is described below.

### External DOC table properties (0.6)

**1114 passed, 18 skipped**, Ruff reported no issues. Skipped tests require
explicit opt-in to LibreOffice. The 64 new synthetic cases check cell operations,
merge order, chains, fallback, lengths, cycles, and limits. Six regular checks
of the project-authored OLE file cover the public API, reproducibility, and
corrupted references; a separate live LibreOffice check confirmed its 3×3
content and structure. That check is included in CI.

3500 mutations (seed 143) and 11 resource checks completed without unexpected
errors. Independent review of the new operations and reference traversal found
no issues. Public DOC/PPT reference fixtures continued to match LibreOffice.

All five personal DOC files parsed. Character counts, table counts, and the set
of previously identified differences from the reference remained unchanged;
full equivalence is not claimed. In two documents, 71 PTableProps references are
now processed; conditional-style and preferred-width limitations are reported
separately. Personal files and reports were not published.
Research: `research-doc-external-tables.md`.

### XLS numeric semantics (0.7)

**1305 passed, 19 skipped** in the full suite. A separate live run of the new XLS
and existing reference fixtures for all seven formats: **13 passed**. Ruff reported
no issues. 3500 mutations (seed 143) produced no unexpected exceptions;
11 resource checks passed.

Independent BIFF tests check original numbers, percentage/decimal/grouped/
scientific display text, rounding, extreme finite values, formula caches,
text limits, and explicit rejection of unsupported syntax. The date regression
involving escaped separators was fixed without changing the expected results
of existing fixtures.

The project-authored `xls_formats/numeric_formats.ods/.xls` contain seven numeric
examples. The API and CLI retain the raw value separately from display text:
`0.125` and `12.50%`. LibreOffice CSV in displayed-value mode confirmed all seven
strings; ordinary XLSX value comparisons alone do not replace this check.
The parser does not evaluate formulas, and the warning about potentially stale
caches is retained. Details and limits: `research-xls-formats.md`.


### DOC table positions (0.8)

Full suite: **1362 passed, 19 skipped**. Added independent checks for omitted
positions, inner and vertical merges, nesting, grid-size limits before allocation,
JSON compatibility, and invariants. The project-authored OLE file is checked
through the public API; its generator is reproducible. Independent review found
no issues. 3500 mutations produced no unexpected errors; 11 resource checks
passed. Text and grid dimensions in the project-authored file match LibreOffice;
the report preserves the distinction between an omitted position and an added
empty cell. Details: `research-doc-offsets.md`.


### Explicit XLS literals (0.9)

Full suite: **1539 passed, 20 skipped**. The new project-authored XLS was checked
through the API, CLI, independent ODS source, and LibreOffice displayed-value CSV:
**5 passed** with the oracle enabled. Independent review found no issues;
3500 mutations produced no unexpected errors, and 11 resource checks passed.
Detailed contract and limitations: `research-xls-literals.md`.


### XLS sign sections (0.10)

Full suite: **1960 passed, 21 skipped**. The project-authored XLS was checked
through the API, CLI, and LibreOffice CSV: **5 passed** with the oracle enabled.
Independent review found no issues; a separate synthetic LibreOffice run confirmed
`General;General` behavior. 3500 mutations completed without unexpected exceptions,
and 11 resource checks passed. Contract: `research-xls-sections.md`.


### Adjacent DOC tables, PPT masters, and auxiliary RTF tables (0.11)

Combined suite: **2088 passed, 22 skipped**. Each new path was checked against
independent expectations and a project-authored document. Review led to fixes
for default TPc, master-reference validation, and the cache-reuse budget.
RTF was checked by directly comparing header/footer and footnote cells with
LibreOffice DOCX. The project-authored PPT was confirmed by independent UNO
readback. The DOC fixture shows the documented structural difference from
LibreOffice while all nine cells and word order match; personal documents
are not published.


### Auxiliary ODT tables and XLS conditions (0.12)

Full suite: **2406 passed, 24 skipped**. Live RTF/XLS-condition run:
**300 passed**. A repeated review of the ODT budget added checks that failure
occurs before copying nested repetitions. The XLS probe preserves original
FORMAT bytes to test thresholds without hidden normalization; ambiguous
precision returns the original number with a warning. Earlier CI found that
the number of exported header parts differed between LibreOffice versions;
the oracle now checks each variant's complete table rather than requiring
one XML file.


### DOC frames, ODT inline objects, legacy RTF text, and PPT fields (0.13)

Full suite: **2685 passed, 27 skipped**; Ruff passed. New RTF oracle:
**57 passed**. ODT inline oracle: **41 passed, 1 skipped** (a separate official
schema check); both live comparisons are enabled in CI. PPT: **252 passed**,
including a project-authored binary file with independently verified strings
and flags. The new paths passed independent review. 3500 mutations produced
no unexpected errors; 11 resource checks passed. Text and table metrics for
five personal DOC files matched the previous check; personal files are not published.

DOC frames were checked against format properties; universal agreement with
LibreOffice layout is not claimed. Unsupported automatic PPT fields are not
evaluated. Details: `research-doc-frame-identity.md`, `research-odf-inline-objects.md`,
`research-rtf-legacy-textboxes.md`, `research-ppt-fields.md`.


### Mutations of the expanded project-authored corpus

`tools/check_mutations.py --all-fixtures` checks every supported document in
`tests/fixtures`, including new subdirectories. Counts are aggregated by format;
the name of a saved reproducing input includes its source fixture identifier
so cases in the same format do not overwrite one another. CI retains the
previous baseline run and adds 100 mutations per public example.
This is sampled testing, not proof that there are no defects.


### DOC note relationships, ODT shapes, and XLS format patterns (0.14)

Full suite: **2937 passed, 34 skipped**, Ruff passed. An independent review of
37 authored files in seven formats found no new failures; differences were
limited to note relationships and expected numeric representations. Live checks:
DOC notes **79 passed**, XLS **135 passed**, ODT shapes/research **41 passed,
4 skipped** (separate official schema checks).

3700 mutations of 37 authored files produced no unexpected exceptions;
11 resource checks passed. Note-path construction uses memory proportional to
depth: a regression with 31 levels and 40 030 cells requires less than 1 MiB
of temporary memory. The installed wheel checks all seven formats and agreement
between the metadata and API versions.


### DOC visibility, ODS drawings, and PPT inline literals (0.15)

Full suite: **3124 passed, 36 skipped**, Ruff passed. Live notes oracle:
**94 passed**; it compares notes with the structure of the generated DOC and
its roundtrip, not with the block count from another LibreOffice release.
ODS drawings: **23 passed, 1 skipped** with Calc; PPT: **306 passed**.
Independent review of each new path is complete; five personal DOC files
retained their character and table counts.

4200 mutations of 42 authored files produced no unexpected exceptions;
all 11 resource checks passed. Binary examples of inline PPT fields and ODS
drawings are included in the shared corpus. Conditional table visibility
is not yet claimed to be supported.


### Conditional DOC visibility and PPT comments (0.16)

Full suite: **3507 passed, 37 skipped**, Ruff passed. DOC-note and PPT-comment suites with live reference checks enabled:
**111 passed**; two tests invoke LibreOffice directly. CI with a newer LibreOffice confirmed the
notes comparison after the AlternateContent selection fix; the original table
is retained in the model, and the special transformation is checked only for
the project-authored reference document.

4600 mutations of 46 authored files and 3500 mutations of the baseline corpus
completed without unexpected exceptions. All 11 resource checks passed.
An invalid OLE entry type is checked before its size is read; separate regressions
cover required and optional DOC/PPT/XLS streams. The installed wheel was checked
outside the source tree for all seven formats. Five personal DOC files retained
their previous character and table counts; their content is not included in
the repository.

Conditional visibility is limited to proven complete rectangular tables;
this is not a claim to support all conditional styles. Details and independent
reference fixtures: `research-doc-conditional-styles.md`, `research-ppt-comments.md`.


### DOC comments, hidden XLS displays and literal RTF WordArt (0.17)

The combined suite passed **3804 tests**, with **51 optional checks skipped**
in the ordinary run; Ruff passed. With live LibreOffice checks enabled, the
DOC-comment suite passed **95 tests**, the hidden-XLS suite **93**, and the
RTF fallback/WordArt suites **122**. These totals include unit and saved-fixture
checks, not just converter invocations.

The new DOC fixture preserves three comments, two authors, duplicate body text,
source CPs 20/38/61 and verified ordinary ranges, including a cell anchor and an
astral character before a reference. Independent review covered missing or
malformed ownership records, metadata limits, note compatibility and linear
anchor collection. A separate model review checked serialization and combined
note/comment path budgets.

All 31 preserved-XLS displays match independent LibreOffice readback; raw numeric
and string values remain available even when their display is empty. Independent
section-selection and whole-mask rejection probes supplement the regression suite.
RTF WordArt has positive authored readback for the explicitly enabled subset.
Fallback-only observations remain a documented boundary, not recovered content.
Oversized inactive candidates do not reject valid body text; accepted oversized
candidates still fail the text limit.

Post-integration checks passed **6000 mutations of 60 authored documents** using
seed 20261022, **3500 baseline mutations** using seed 143, and all **11 resource
checks**. Five private DOC documents retained their previous character/table
counts. No private document contents were published. Before this work, the 0.16
baseline separately passed 23,000 mutations with seed 20261022; that earlier run
is not included in the post-integration totals.

The installed 0.17 wheel passed all seven formats outside the source tree,
including DOC comment ownership and hidden XLS raw values. The source archive
contains all 127 tracked fixture files, including DOCX/XLSX/FODT reference sources
and CSV observations; no private `tmp/` data is included.

## Unicode WordArt validation (0.18)

The full local suite passed **3,921 tests**, with **60 optional skips**. Ruff
passed; 6,900 deterministic mutations over 69 public fixtures produced no
unexpected exceptions. All 12 bounded resource checks passed, including a
100,000-escape Unicode property with a 128-character output budget and a lexical
budget large enough to reach the deferred property-overflow check.

The WordArt/fallback/Unicode/API suites passed **201 tests** with live reference
checks enabled, including nine new authored Unicode fixtures. Windows-1252,
Windows-1251 and Shift-JIS examples matched LibreOffice 7.4.7.2. The Unicode
suite is also included in the CI reference job. Public API/CLI tests preserve
Unicode and suppress duplicate fallback content; the installed-wheel check
covers Unicode, Cyrillic and Japanese fixtures outside the source import path.
See [the exact supported grammar](research-rtf-fallback-text.md).

## XLS text sections and DOC selections (0.19)

The full local suite passed **4,172 tests**, with **62 optional skips**; Ruff
passed. **7,100** deterministic mutations of 71 public fixtures produced no
unexpected exceptions, and all **12** bounded resource checks passed.

The XLS suite passed 1,496 tests (8 optional skips), including 132 independent
review cases. Its two live oracle checks verify 12 cell displays against the
same preserved XLS. The DOC selection suite and XLS oracle together passed
36 tests with LibreOffice enabled. Independent DOC review added 43 boundary
cases and checked source-coordinate isolation and preprocessing budgets.
The installed-wheel smoke check includes both new fixture families.

See [XLS text affixes](research-xls-text-sections.md) and
[DOC selection ranges](research-doc-comment-selections.md) for exact supported
subsets and reproducible evidence. Older formats, arbitrary text masks and
unproven structural crossings are not covered by these results.

## DOC replies and literal XLS displays (0.20)

The full local suite passed **4,483 tests**, with **64 optional skips**; Ruff
passed. **7,400** deterministic mutations of 74 public fixtures produced no
unexpected exceptions, and all **12** bounded resource checks passed.

Independent XLS review passed 1,758 tests (9 optional skips), including 133 new
review cases. All 13 literal-display fixture cells match the same preserved XLS
converted to CSV. Independent DOC review passed 1,214 tests (6 optional skips),
including 15 review regressions and the fixed public preorder validation.
The DOC-reply and XLS-oracle modules together passed 37 tests with live
LibreOffice checks enabled. The DOC conversion records loss of reply links,
not proof of full Word conformance or LibreOffice reply support.

All 71 previous fixture results remain unchanged after removing only the new
reply metadata keys for comparison. Five existing comments in two DOC fixtures
now explicitly identify their stored root depth. The installed-wheel checks
include both new fixture families and unchanged text projection.
See [DOC replies](research-doc-comment-replies.md) and
[XLS literal displays](research-xls-text-literals.md) for scope and evidence.

## Behavior-preserving refactoring (0.20.1)

The full local suite remains **4,483 passed, 64 skipped**, and Ruff passes.
All **74** public fixture JSON digests are identical before and after the change.
The four extracted output validators have identical Python ASTs; their existing
internal result-validator import remains available from `api`.

The preserved-XLS helper refactor removes 151 duplicated lines. All nine files
in the three fixture families remain byte-identical, and all six tests in their
live LibreOffice suites pass. Literal expectations, hashes, FORMAT/XF checks,
source-byte preservation, test names, and opt-in gates are unchanged. Installed
wheel and source-archive checks cover the new internal validation module and
shared test helper.

## Parser state refactoring (0.20.2)

The full suite remains **4,483 passed, 64 skipped**, and Ruff passes. All **74**
public fixture JSON digests are unchanged. The selected DOC/RTF reference suites
pass **441 tests** with their live LibreOffice checks enabled. All **12** bounded
resource checks pass.

Independent reviewers approved both extractions. A deterministic differential
check covered **9,292 paired outcomes** from 46 public DOC/RTF fixtures, each
original plus 100 mutations under two limit profiles. Full JSON results or
exception types/messages matched, with no timeouts or worker failures.
Additional focused reviews matched **2,496** RTF fixture/mutation/limit outcomes
and **10,000** DOC reference-observation cases, including property-call ordering,
field state, warnings, visibility and anchors. These are bounded samples, not
proof of equivalence for every possible document.

## DOC heading levels and adapter guidance (0.21)

The full suite passes **4,839 tests**, with **65 optional skips**; Ruff passes.
The original **74** public fixture JSON results remain unchanged. The new
heading fixture has independent literal expectations, a deterministic source,
raw STSH/CLX/PAPX evidence and saved LibreOffice readback. Its text projection
matches the pre-heading parser exactly; metadata remains in its source cells
and stories. The heading/parser/API suites pass **111 tests** with live
LibreOffice enabled.

Independent review corrected ancestor-versus-selected-style precedence and
rechecked inherited body/outline operands. Model validation rejects invalid
levels, including booleans. Additional retention checks cover exact text limits,
comment anchor paths and bounded style caches. **7,500** deterministic mutations
of 75 public fixtures produced no unexpected exceptions; all **12** bounded
resource checks passed. Sampling does not establish correctness for every input.

LibreOffice 7.4 loses one custom style's inherited heading on resave; this is
recorded explicitly and does not replace the binary source's independent
expectation. See [DOC heading evidence](research-doc-headings.md) and
[adapter guidance](INTEGRATION.md). Heading-path construction and XLS header
selection belong to consumers; they are not inferred by the library.

## Terminal and reserved-range compatibility (0.21.1)

The full suite passes **4,886 tests**, with **65 optional skips**; Ruff passes.
All **75** existing public fixture JSON results remain unchanged. **7,500**
deterministic mutations produced no unexpected exceptions; all **12** bounded
resource checks pass. New regressions are original synthetic inputs.

A local corpus of 47 files (36 distinct byte hashes) initially produced 42
successful parses. With the compatibility fixes, 45 parse at the default record
ceiling; an explicit 500,000-record profile parses 46. The remaining container
has no supported office document stream. The corpus classification run allowed
128 MiB input solely to classify that large container; this is not a changed
library default. All 42 previously successful JSON results are identical.
No private file, source text, name or identifier is included in the repository.

The large synthetic DOC stress case requires 264,799 record-budget units and
produces 967,485 text characters. The 200,000 default remains unchanged; the
[consumer resource profile](INTEGRATION.md#resource-profiles-for-large-documents)
raises only the record ceiling. These observations are not general time/memory
guarantees for arbitrary inputs.

Independent RTF review checked 7,381 short trailers plus chunk, malformed-root,
concatenated-document and budget boundaries. Only a single physical terminal
NUL gains acceptance, with a warning and unchanged text. CLI strict mode still
reports that warning. Independent DOC review checked 12,000 synthetic range
layouts and main/header integration cases; live endpoints stay story-bounded,
and reserved or reusable text stays excluded. Bounded local LibreOffice readback
confirmed the affected live textbox content after whitespace normalization.
The final CP domain boundary is covered explicitly. Sampling is not exhaustive.

## RTF and ODT heading metadata (0.22.0)

The full suite passes **5,048 tests**, with **68 optional skips**; Ruff passes.
All **75** pre-existing public fixture JSON results remain unchanged. The three
new original heading fixtures have separate independent source/readback and
parser-policy expectations; all three live LibreOffice 7.4 readbacks pass. See
[RTF/ODT heading evidence](research-rtf-odt-headings.md).

**7,800** deterministic mutations over the expanded 78-fixture corpus produced
no unexpected exceptions. All **12** bounded resource checks pass. Independent
RTF regressions cover suppressed style metadata, consecutive empty cells and
implicit nested-table boundaries. ODT regressions cover invalid and unsupported
levels across body, cells and stories, including very long numeric attributes.

The same local 47-file corpus, with the documented 500,000-record/128 MiB
classification profile, still produces 46 documents and one unsupported
container. Plain-text hashes are unchanged for every successful document.
Structured output adds 73 RTF and 37 ODT heading levels; RTF name inference is
reported by a warning. These counts do not establish correctness of every
heading or downstream chunk count. Private content remains outside the repository.

The [output format reference](OUTPUT_FORMAT.md) documents all seven families and
serialization omissions. Its four synthetic JSON examples match model validation
and serialization.
