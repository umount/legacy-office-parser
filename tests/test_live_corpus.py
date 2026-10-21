"""Opt-in, seven-format LibreOffice comparison of original public documents."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in seven-format LibreOffice oracle')
@pytest.mark.parametrize('name', [
    'ordinary_table.doc', 'merged_table.doc', 'slides_notes.ppt',
    'extended/ordinary_table.rtf', 'extended/ordinary_table.odt',
    'extended/merged_table.odt', 'extended/typed_sparse.xls',
    'extended/typed_sparse.ods', 'extended/slides_notes.odp',
])
def test_original_fixture_reference(name):
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'tools' / 'check_corpus.py'),
         str(FIXTURES / name), '--libreoffice', '--timeout', '30'],
        capture_output=True, text=True, timeout=70, cwd=ROOT)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report, = json.loads(completed.stdout)['files']
    differences = report['reference_differences']
    if name == 'extended/typed_sparse.xls' and differences:
        # Proven conversion artifact: this ORIGINAL fixture contains two BOOLERR
        # literals, which LO may rewrite as TRUE()/FALSE() formulas in XLSX.
        # Independent fixture tests verify the source values and formula flags.
        # Do not generalize this allowance to private/unseen XLS documents.
        assert differences == ['reference_spreadsheet_inconclusive']
        comparison = report['reference_spreadsheet']
        assert comparison['status'] == 'ambiguous'
        assert comparison['counts'] == {'conversion_boolean_formula': 2}
        assert comparison['issues'] == [
            {'reason': 'conversion_boolean_formula', 'sheet': 1, 'coordinate': [2, 4]},
            {'reason': 'conversion_boolean_formula', 'sheet': 1, 'coordinate': [6, 3]},
        ]
        assert comparison['compared_cells'] == comparison['cells'] == comparison['reference_cells'] == 11
    else:
        assert differences == [], report
