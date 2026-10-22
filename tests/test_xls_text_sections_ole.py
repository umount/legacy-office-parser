"""Authored same-XLS oracle; exact short FORMAT strings patched after export."""
import hashlib
import os
from pathlib import Path

import pytest

import _xls_format_oracle as oracle

from test_xls_text_sections import CASES as TEXT_CASES

FIXTURE = Path(__file__).parent / 'fixtures/xls_text_sections/preserved.xls'
CASES = [(code, 'retained', expected) for code, expected in TEXT_CASES]
CASES += [('0;0;0;"Name: "@', 12, '12'),
          ('0;0;0;"Name: "@', -12, '12'),
          ('0;0;0;"Name: "@', 0, '0')]


# Preserve the family-level entry points used by fixture research commands.
def verify_file(path):
    return oracle.verify_file(path, CASES)


def verify_csv(path, destination):
    return oracle.verify_csv(path, destination, CASES)


def generate_preserved(destination):
    return oracle.generate_preserved(destination, CASES)


def test_persisted_exact_formats_and_public_api():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == '30ab890bbb3b650a51b97197ded8aa0fe75250a7057131423f89a04938ba4793'
    verify_file(FIXTURE)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in exact FORMAT export/patch/CSV oracle')
def test_regenerated_and_persisted_oracles(tmp_path):
    generate_preserved(tmp_path / 'generated')
    destination = tmp_path / 'persisted'
    destination.mkdir()
    verify_csv(FIXTURE, destination)
