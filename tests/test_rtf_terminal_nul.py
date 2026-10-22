"""Original synthetic inputs for the single terminal-NUL compatibility boundary."""
import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from legacy_office_parser.rtf import parse_rtf_bytes

WARNING = 'A single terminal NUL after the RTF root was ignored.'
ROOT = br'{\rtf1\ansi Original}'


def parse(data, **limits):
    return parse_rtf_bytes(data, Limits(**limits))


@pytest.mark.parametrize('space', [b'', b' ', b'\t', b'\r\n', b' \t\r\n '])
@pytest.mark.parametrize('chunk', [8, 100])
def test_single_physical_terminal_nul_after_complete_root(space, chunk):
    plain = parse(ROOT + space, max_text_chars=chunk)
    terminated = parse(ROOT + space + b'\0', max_text_chars=chunk)
    assert terminated.blocks == plain.blocks
    assert terminated.text == 'Original'
    assert terminated.warnings == plain.warnings + [WARNING]


@pytest.mark.parametrize('suffix', [
    b'\0\0', b'\0\r\n', b'\0 ', b'\0X', b'X\0', b'\0 X\0', b'\0\n\0',
    br"\'00", br"\'00"+b'\0', br'\u0?'+b'\0', br'\bin1 '+b'\0',
    b'}\0', br'{\rtf1 Second}'+b'\0', br'\unknown'+b'\0',
])
def test_other_trailing_data_remains_rejected(suffix):
    with pytest.raises(InvalidDocumentError):
        parse(ROOT + suffix)


@pytest.mark.parametrize('source', [br'{\rtf1 Unclosed'+b'\0',
                                    br'{\rtf1 Escaped\}'+b'\0',
                                    br'{\rtf1{\*\object x}'+b'\0'])
def test_nul_does_not_repair_unclosed_root(source):
    with pytest.raises(InvalidDocumentError):
        parse(source)


def test_full_input_and_lexical_limits_include_terminator():
    source = ROOT + b'\0'
    for limit in ['max_file_bytes', 'max_stream_bytes']:
        with pytest.raises(LimitExceededError):
            parse(source, **{limit:len(ROOT)})
    # open, rtf, ansi, bytes, close: the NUL is the sixth lexical record.
    assert parse(ROOT, max_records=5).text == 'Original'
    with pytest.raises(LimitExceededError, match='lexical'):
        parse(source, max_records=5)
    with pytest.raises(LimitExceededError, match='text'):
        parse(source, max_text_chars=7)


def test_existing_unicode_and_story_behavior_preserved():
    source = br'{\rtf1\ansi\uc1\u-10179?\u-8704?{\header Header}\par}'
    plain = parse(source)
    terminated = parse(source+b'\0')
    assert terminated.text == plain.text
    assert terminated.headers_footers == plain.headers_footers == 'Header'
    assert terminated.warnings == plain.warnings + [WARNING]
