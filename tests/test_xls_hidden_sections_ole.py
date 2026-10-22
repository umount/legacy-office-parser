"""Authored same-XLS oracle; exact short FORMAT strings patched after export."""
import hashlib
import os
from pathlib import Path

import pytest

import _xls_format_oracle as oracle

from test_xls_hidden_sections import CASES as NUMERIC_CASES

FIXTURE = Path(__file__).parent / 'fixtures/xls_hidden_sections/preserved.xls'
CASES = [(code, value, expected) for code, outputs in NUMERIC_CASES if len(code) >= 3
         for value, expected in zip((12, -12, 0), outputs)]
CASES += [(';;;', 'retained', ''), ('0;0;0;', 'retained', ''),
          (';;;@', 'retained', 'retained'), ('0;;0', 'retained', 'retained')]


# Preserve the family-level entry points used by fixture research commands.
def verify_file(path):
    return oracle.verify_file(path, CASES)


def verify_csv(path, destination):
    return oracle.verify_csv(path, destination, CASES)


def generate_preserved(destination):
    return oracle.generate_preserved(destination, CASES)


def test_persisted_exact_formats_and_public_api():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == '3add5107121667889ec7d2614ae6ca1857fd21e22f2069c7dc30b2f6fa0819cb'
    verify_file(FIXTURE)


@pytest.mark.skipif(os.environ.get('OFFICE_CORPUS_LIBREOFFICE') != '1',
                    reason='opt-in exact FORMAT export/patch/CSV oracle')
def test_regenerated_and_persisted_oracles(tmp_path):
    generate_preserved(tmp_path / 'generated')
    destination = tmp_path / 'persisted'
    destination.mkdir()
    verify_csv(FIXTURE, destination)
