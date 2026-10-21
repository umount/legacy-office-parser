# Synthetic performance checks

Run from the repository root:

```sh
.venv/bin/python tools/check_performance.py --profile large --repeats 3 \
  --libreoffice /usr/bin/libreoffice
.venv/bin/pytest -q tests/test_performance_tool.py
```

The tool uses the public `parse(path)` API with **unchanged default Limits** and
original synthetic documents only. It requires Linux and no additional Python
dependency. Optional developer LibreOffice converts ODT/ODS/ODP to DOC/XLS/PPT;
it is not a runtime dependency or extraction oracle. Omitting `--libreoffice`
explicitly skips the three binary formats. Inputs and isolated converter profiles
are generated in temporary directories and removed after the run.

Current follow-up: all seven formats pass after `ffe781c`; see the final section.
The earlier 0.5.0 measurements below are retained as historical evidence.

## Workload and correctness

- ODT/RTF/DOC: 3,000 paragraphs followed by one 300 × 6 table. Only the first
  body paragraph selects the ODT master page; all subsequent paragraphs and
  table cells use default styling, without forced per-paragraph section changes.
- ODS/XLS: two sheets, each with 1,500 × 8 explicitly populated string cells
  (24,000 total). No repetition attributes inflate the workload.
- ODP/PPT: 120 slides, each containing eight uniquely identified paragraphs.
- `--profile small` uses 20 paragraphs, a 10 × 6 table, two 20 × 8 sheets and
  five slides. The profiles are fixed to keep generation moderate.

Validation compares every authored paragraph, table cell/dimension, sheet name,
cell coordinate/type/text, and ordered slide text/count against generation rules.
It also checks text-document block order via the public text projection.
Whitespace is normalized; exact line breaks are not validated. Output counts and
warning counts are reported. Any missing, extra or misplaced content fails;
**any warning also causes strict `validation_failed`, independently of content**.

The synthetic language compresses well: these are large logical workloads, not
large compressed ODF files. JSON reports actual input bytes and ODF uncompressed
archive bytes. This does not cover images, formulas, nested tables, complex layout,
embedded objects, multilingual text or arbitrary real documents. Native ZIP bytes
are deterministic; converted binary metadata can vary with LibreOffice.

## Metrics and containment

Each file/repeat uses a fresh sequential worker. `parse_seconds` includes input I/O
inside `parse(path)` and excludes imports, conversion, validation and serialization.
`subprocess_seconds` includes startup and validation. Filesystem caches are not
flushed. `peak_rss_kib` is Linux `/proc/self/status` VmHWM immediately after parse:
the current interpreter/imports and parse peak, before validation allocations.
It excludes converter memory and is neither a memory delta nor a leak test.
`ru_maxrss` is avoided because it can retain a parent's pre-exec high-water mark.

Workers have a 384 MiB address-space cap, 30 CPU seconds and a 45-second wall
deadline (`--timeout` permits `(0, 60]`). Converter workers have a 1 GiB
address-space cap, 60 CPU seconds and 90-second wall deadline. Core dumps are
disabled. CPU/memory limits are per process; wall deadlines cover private process
groups. Each group is killed and its direct child reaped on completion, timeout
or interruption. Host termination of the harness itself can prevent cleanup.
At most three repeats and 5 MiB per input are allowed. These are containment
budgets, **not performance acceptance thresholds**.

Failures remain visible; conversion failures never fall back to smaller fixtures.
Unavailable metrics are null. Parse errors expose their type, not arbitrary
exception text; the exact DOC record-budget rejection has safe code
`doc_record_budget`. JSON includes full parser defaults, generated input hashes,
project/runtime versions and parser-source hashes before/after the run. No source
text or corpus paths are reported. Exit status is nonzero for failures, including
PPT's conservative warning; `skipped` is explicit and does not fail the command.

## Final measurements — 2026-10-21

Version 0.5.0, including nested DOC tables and section-boundary handling.
Python 3.12.14, Linux 6.1.0-53-amd64 x86_64 / glibc 2.36,
LibreOffice 7.4.7.2 40(Build:2). Three fresh workers per format;
hardware and host load were not controlled. Parser-source SHA-256 was unchanged
before and after the run: `7cc8a4076c0a7e4979cecb2a8865e6bf878773872c71207539f543aa9276fc84`.

The following are all three raw samples: parse seconds, then peak RSS KiB.

- **ODT** — 18,140 input bytes; `ok`.
  Seconds: 0.172158, 0.153097, 0.178173.
  RSS KiB: 26504, 26364, 26332.
  Counts: paragraphs=3000, tables=1, table_rows=300, table_cells=1800, text_chars=643799, warnings=0.

- **RTF** — 705,019 input bytes; `ok`.
  Seconds: 0.194326, 0.180270, 0.162413.
  RSS KiB: 23832, 25840, 24296.
  Counts: paragraphs=3000, tables=1, table_rows=300, table_cells=1800, text_chars=643799, warnings=0.

- **ODS** — 71,403 input bytes; `ok`.
  Seconds: 0.873340, 0.868909, 0.813871.
  RSS KiB: 42256, 42204, 42308.
  Counts: sheets=2, sheet_cells=24000, text_chars=750302, warnings=0.

- **ODP** — 5,329 input bytes; `ok`.
  Seconds: 0.035575, 0.043392, 0.036550.
  RSS KiB: 23792, 23328, 25844.
  Counts: slides=120, text_chars=125878, warnings=0.

- **DOC** — 1,669,120 input bytes; `ok`.
  Seconds: 1.645374, 1.652079, 1.566416.
  RSS KiB: 32584, 32508, 32600.
  Counts: paragraphs=3000, tables=1, table_rows=300, table_cells=1800, text_chars=643799, warnings=0.

- **XLS** — 1,083,392 input bytes; `ok`.
  Seconds: 0.270582, 0.233954, 0.321262.
  RSS KiB: 32412, 32488, 32472.
  Counts: sheets=2, sheet_cells=24000, text_chars=750302, warnings=0.

- **PPT** — 1,084,928 input bytes; `validation_failed`.
  Seconds: 0.037458, 0.027057, 0.022585.
  RSS KiB: 24496, 24116, 24176.
  Counts: slides=120, text_chars=125878, warnings=1.

Large ODT/ODS/ODP uncompressed archive bytes: 847,861, 2,675,724, 166,454, respectively.

ODT, RTF, ODS, ODP, DOC and XLS pass every content/structure check without
warnings in all three runs. DOC returns all 3,000 top-level paragraphs and the
300 × 6 table; it does not exhaust default `max_records=200000`. No parser
hits a resource limit or timeout. These observations are not a universal
throughput guarantee or evidence of completeness beyond the authored workload.

PPT matches all 120 slides and all authored text (125,878 projected characters).
Its sole failed check is the conservative warning: “PPT extension records are not
extracted; extension-only content may be omitted.” It remains **strict
`validation_failed`** in all three runs, and the benchmark command exits 1.

Tool verification: **17 tests passed**, including first-body-paragraph-only master
selection, content loss/reordering and coordinate corruption, deterministic input
bytes, metrics, private-error suppression, converter failure/skip handling,
deadline validation and descendant timeout cleanup. Ruff passed for the two
sidecar Python files. No production parser code or defaults were changed.

Section-boundary regressions are stored in `tests/fixtures/doc_sections/`.

## Follow-up: PPT metadata classification (`ffe781c`)

The same large workload was run three times per format after the narrow PPT
metadata classifier was added. Python 3.12.14, Debian Linux 6.1.0-53-amd64,
LibreOffice 7.4.7.2, unchanged parser defaults. All **21 runs returned `ok`**,
without warnings, timeouts or validation errors; the command exited zero.
Source hash before/after was identical:
`ccacba7b7a59d06c1c8875a9dfd2789700acbc887a9e69721da5798e4160e263`.

PPT: 1,084,928 input bytes, 120 slides, 125,878 projected characters.
Parse seconds: 0.029576, 0.030067, 0.029384.
Peak RSS KiB: 24172, 24472, 24088. All authored text and ordering checks pass.

The former warning came from fixed numeric timing metadata in `___PPT10`
records. Unknown or potentially text-bearing extensions still warn. This result
does not extend the completeness claim beyond the authored workload; see
`research-ppt-extensions.md` for the classifier's exact boundary.
