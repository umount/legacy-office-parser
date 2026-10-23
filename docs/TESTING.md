# Testing

## Local workflow

Install development dependencies once, then run the tests for the changed behavior:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q tests/test_doc_header_ranges.py
ruff check src tests tools
```

Do not run the full suite, public corpus, mutation campaign, resource checks and
package build after every small edit. CI runs the full suite on Python 3.11–3.13
and the configured reference checks after push. Its definition is authoritative:
[workflow](../.github/workflows/test.yml).

## Test organization

- Format rules: literal synthetic cases at the smallest useful parser/helper boundary.
- Integration: representative record types, source ownership and serialization.
- Regressions: one minimal reproduction per reported failure, plus necessary boundaries.
- Resource checks: retain exact limits and malformed/truncated input cases.
- Reference fixtures: original source and expected output; LibreOffice is a
  development comparator, never the source of production expected values.

Avoid multiplying every numeric value by every transport, style, or output
location when these exercise independent logic. Keep interactions that matter
(signed zero, cache/raw-value preservation, builtin/custom format dispatch).
Do not hide redundant work in loops or remove security checks to lower a count.

`tests/_xls_format_oracle.py` shares preserved FORMAT/XF mechanics. Format
fixtures retain their builders/readback helpers. See the seven format pages for
support and limitations; old test counts and progress reports live in Git history.

## Optional investigations

Run only when relevant to a change or an explicit report:

```sh
python tools/check_mutations.py --all-fixtures --cases-per-format 100
python tools/check_security_resources.py
python tools/check_performance.py --profile large --repeats 3
python -m build
```

Private inputs and reports belong in ignored `tmp/`. Never commit their text,
converted files or snapshots. `tools/check_corpus.py tmp --libreoffice` can compare
local inputs, but word/hash agreement alone does not prove structure or fidelity.
