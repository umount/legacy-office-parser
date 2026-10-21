import pytest
from legacy_office_parser import Limits, LimitExceededError, InvalidDocumentError
from legacy_office_parser.api import _read, _validate_result
from legacy_office_parser._ole import open_ole
from legacy_office_parser.models import Cell, Document, Paragraph, Table, Slide

@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_invalid_limits(value):
    with pytest.raises(ValueError):
        Limits(max_records=value)

def test_file_read_is_bounded(tmp_path):
    p = tmp_path / 'input.doc'
    p.write_bytes(b'x' * 20)
    with pytest.raises(LimitExceededError):
        _read(p, Limits(max_file_bytes=19))
    assert len(_read(p, Limits(max_file_bytes=20))) == 20

def test_reject_non_ole():
    with pytest.raises(InvalidDocumentError):
        with open_ole(b'not a compound file', Limits()):
            pytest.fail('invalid container accepted')

def test_aggregate_output_budget_includes_notes_and_cells():
    doc = Document(format='doc', blocks=[Paragraph('abc'), Table([[Cell('def')]])], footnotes='ghi')
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_text_chars=8))
    assert _validate_result(doc, Limits(max_text_chars=9)) is doc

def test_cell_budget():
    doc = Document(format='doc', blocks=[Table([[Cell(''), Cell('')]])])
    with pytest.raises(LimitExceededError):
        _validate_result(doc, Limits(max_cells=1))

def test_blank_slides_keep_number_in_json():
    doc = Document(format='ppt', slides=[Slide(1, text='first'), Slide(2), Slide(3, notes='note')])
    assert [s['number'] for s in doc.to_dict()['slides']] == [1, 2, 3]
