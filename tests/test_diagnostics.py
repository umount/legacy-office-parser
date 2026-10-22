"""Codes are attached at emission sites and survive legacy string/pickle paths."""
import ast
import json
from pathlib import Path
import pickle

from legacy_office_parser import Document, parse, parse_rtf
from legacy_office_parser._diagnostic_codes import DIAGNOSTIC_CODES
from legacy_office_parser.diagnostics import CodedWarning, diagnostic_warning


def test_heading_fallback_code_and_legacy_message():
    doc = parse_rtf(br'{\rtf1{\stylesheet{\s1 Heading 1;}}\s1 Title}')
    assert doc.warnings == ['RTF heading levels inferred from built-in style names.']
    assert doc.diagnostics[0].code == 'heading_name_fallback'
    assert doc.to_dict()['diagnostics'] == [{
        'code': 'heading_name_fallback', 'message': doc.warnings[0]}]
    assert json.loads(json.dumps(doc.to_dict()))['warnings'] == doc.warnings


def test_hidden_text_has_stable_code_and_is_deduplicated():
    doc = parse_rtf(br'{\rtf1 A{\v secret}{\deleted other}B}')
    assert doc.text == 'AB'
    assert [d.code for d in doc.diagnostics] == ['hidden_text_omitted']


def test_manual_uncoded_warnings_remain_representable():
    doc = Document('rtf', warnings=['custom', 'custom'])
    assert doc.warnings == ['custom', 'custom']
    assert doc.to_dict()['diagnostics'] == [{'code': 'unclassified_warning', 'message': 'custom'}]
    assert 'diagnostics' not in Document('rtf').to_dict()


def test_codes_survive_pickle_and_are_not_mutable():
    import pytest
    warning = diagnostic_warning('example_code', 'same text')
    copied = pickle.loads(pickle.dumps(warning))
    assert copied == warning and copied.code == warning.code
    with pytest.raises(AttributeError):
        copied._code = 'changed'
    with pytest.raises(AttributeError):
        del copied._code
    assert copied.code == 'example_code'
    assert CodedWarning('another_code', 'same text') == warning
    doc = Document('rtf', warnings=[warning, CodedWarning('another_code', 'same text')])
    assert len(doc.diagnostics) == 2


def test_every_library_warning_site_has_an_explicit_registered_code():
    root = Path(__file__).parents[1] / 'src/legacy_office_parser'
    found = set()
    for path in root.glob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == 'diagnostic_warning':
                assert isinstance(node.args[0], ast.Constant), (path, node.lineno)
                code = node.args[0].value
                assert code in DIAGNOSTIC_CODES, (path, node.lineno, code)
                found.add(code)
            if not node.args:
                continue
            warn = ((isinstance(node.func, ast.Attribute) and node.func.attr == 'warn') or
                    (isinstance(node.func, ast.Name) and node.func.id == 'warn'))
            if warn and not isinstance(node.args[0], ast.Name):
                assert isinstance(node.args[0], ast.Call), (path, node.lineno)
                assert getattr(node.args[0].func, 'id', None) == 'diagnostic_warning'
    assert 'heading_name_fallback' in found


def test_public_corpus_has_no_uncoded_library_warnings():
    root = Path(__file__).parent / 'fixtures'
    for path in root.rglob('*'):
        if path.suffix not in {'.doc', '.xls', '.ppt', '.rtf', '.odt', '.ods', '.odp'}:
            continue
        doc = parse(path)
        assert all(d.code in DIAGNOSTIC_CODES and d.code != 'unclassified_warning'
                   for d in doc.diagnostics), path
