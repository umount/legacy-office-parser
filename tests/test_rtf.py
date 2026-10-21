"""Original synthetic RTF fixtures; no private documents or upstream fixtures."""
import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError, ParseError
from legacy_office_parser.limits import Limits
from legacy_office_parser.models import Paragraph, Table
from legacy_office_parser.rtf import parse_rtf_bytes


def parse(body, **limits):
    if isinstance(body, str):
        body = body.encode('ascii')
    return parse_rtf_bytes(b'{\\rtf1 ' + body + b'}', Limits(**limits))


def test_paragraphs_and_symbols():
    d = parse(r'one\tab two\line three\par\par \{x\}\\\~\_\-\emdash\endash')
    assert d.format == 'rtf'
    assert [b.text for b in d.blocks] == ['one\ttwo\nthree', '', '{x}\\\xa0\u2011\xad—–']


def test_groups_and_codepages():
    d = parse(r"\ansicpg1251 \'cf{\ansicpg1252 \'e9}\'f0")
    assert d.text == 'Пéр'


def test_font_table_default_scope_and_explicit_override():
    d = parse(r"\deff1{\fonttbl{\f0\fcharset0 Latin;}"
              r"{\f1\cpg1251\fcharset128 Cyrillic;}{\f2\fcharset128 Japanese;}}"
              r"\'cf{\f0\'e9}{\f2\'82\'a0}\'f0\plain\'e8")
    assert d.text == 'Пéあри'
    assert not d.warnings


@pytest.mark.parametrize('encoding,text', [('cp932', '日本'), ('gbk', '中文'), ('cp950', '中文')])
def test_multibyte_hex(encoding, text):
    cp = {'cp932': 932, 'gbk': 936, 'cp950': 950}[encoding]
    escaped = ''.join("\\'%02x" % b for b in text.encode(encoding))
    assert parse('\\ansicpg%d %s' % (cp, escaped)).text == text


def test_mixed_raw_hex_and_chunk_boundary():
    assert parse(b"\\ansicpg932 \x82\\'a0").text == 'あ'
    d = parse(b'\\ansicpg932 ' + b'a' * 4095 + b"\\'82\\'a0")
    assert d.text == 'a' * 4095 + 'あ'


@pytest.mark.parametrize('fallback', [r'?', r"\'3f", r'\~', r'\tab ', r'\b ', r'\{', r'\bin3 {}x'])
def test_unicode_fallback_tokens(fallback):
    assert parse(r'\u945' + fallback + 'Z').text == 'αZ'


def test_unicode_fallback_scoping_and_braces():
    assert parse(r'\uc2\u945??{\uc0\u946}\u947??').text == 'αβγ'
    assert parse(r'\uc3\u945?{X}Y').text == 'αXY'
    assert parse(r'\uc2\u945\b\i Z').text == 'αZ'
    assert parse(r'\uc1\u945' + '\r\n?Z').text == 'αZ'


def test_surrogates():
    d = parse(r'\u-10179?\u-8704?')
    assert d.text == '😀'
    assert not d.warnings
    assert parse(r'\uc0\u55357{\b\u56832}').text == '😀'
    d = parse(r'\u-10179?x\u-8704?\u-10179?')
    assert d.text == '\ufffdx\ufffd\ufffd'
    assert any('surrogate' in w for w in d.warnings)


def test_destinations_and_field_results_never_reenable_skip():
    d = parse(r'A{\*\unknown SECRET{\fldrslt STILLSECRET}}'
              r'{\pict 89504E47{\fldrslt SECRET}}'
              r'{\object{\objdata 012345}{\result SECRET}}'
              r'{\field{\*\fldinst HYPERLINK "https://example.test"}'
              r'{\fldrslt visible {\b link}}}Z')
    assert d.text == 'Avisible linkZ'
    assert len(d.warnings) == 2


def test_binary_is_exact_and_opaque():
    payload = b'{}\\par\x00\xff{'
    d = parse(b'A{\\pict\\bin' + str(len(payload)).encode() + b' ' + payload + b'}Z')
    assert d.text == 'AZ'
    assert parse(b'A\\bin3 {}xZ').text == 'AZ'
    assert parse(b'A\\bin0 Z').text == 'AZ'


def test_stories_separate_and_endnote():
    d = parse(r'Body{\header Head\par Next}{\footer Foot}'
              r'{\footnote Note}{\footnote\ftnalt End} tail')
    assert d.blocks == [Paragraph('Body tail')]
    assert d.headers_footers == 'Head\nNext\nFoot'
    assert d.footnotes == 'Note'
    assert d.endnotes == 'End'


def test_upr_and_optional_unicode_destination():
    assert parse(r'{\upr{ANSI}{\*\ud Unicode \u945?}}').text == 'Unicode α'
    assert parse(r'{\*\unknown{\upr{ANSI}{\*\ud SECRET}}}ok').text == 'ok'


def test_hidden_and_plain():
    d = parse(r'A{\v hidden}B{\deleted removed}\v hidden\plain C')
    assert d.text == 'ABC'
    assert d.warnings


def test_tables_empty_cells_rows_and_paragraph_order():
    d = parse(r'before\par\trowd\cellx100\cellx200\intbl A\cell\cell\row'
              r'\trowd\cellx100\cellx200\intbl B\par C\cell D\cell\row'
              r'\pard after')
    assert len(d.blocks) == 3
    assert d.blocks[0] == Paragraph('before')
    t = d.blocks[1]
    assert isinstance(t, Table)
    assert [[c.text for c in row] for row in t.rows] == [['A', ''], ['B\nC', 'D']]
    assert d.blocks[2] == Paragraph('after')


def test_merge_warning_and_trailing_empty_cell_recovery():
    d = parse(r'\trowd\clmgf\cellx100\clmrg\cellx200\clvmgf\cellx300 X\cell\row')
    assert [c.text for c in d.blocks[0].rows[0]] == ['X', '', '']
    assert any('Merged' in w for w in d.warnings)
    assert all(c.col_span == 1 for c in d.blocks[0].rows[0])


def test_nested_table_warning():
    d = parse(r'\trowd\cellx100\itap2 a\nestcell b\nestrow c\cell\row')
    assert d.blocks[0].rows[0][0].text == 'a\tb\nc'
    assert any('Nested' in w for w in d.warnings)


def test_incomplete_row_recovered_and_story_table():
    d = parse(r'\trowd x\cell y')
    assert [c.text for c in d.blocks[0].rows[0]] == ['x', 'y']
    assert any('Incomplete' in w for w in d.warnings)
    d = parse(r'{\header\trowd a\cell b\cell\row}body')
    assert d.headers_footers == 'a\tb'
    assert d.blocks == [Paragraph('body')]


def test_unknown_codepage_and_bad_encoded_text_warn():
    d = parse(r"\ansicpg99999 \'e9")
    assert d.text == 'é' and d.warnings
    d = parse(r"\ansicpg932 \'82")
    assert d.text == '\ufffd' and d.warnings


@pytest.mark.parametrize('data', [b'', b'text', b'{\\rtf2 hi}', b'{\\rtf10 hi}',
    b'{\\rtf1 hi', b'{\\rtf1 hi}}', b'{\\rtf1 hi}junk', b'{\\rtf1\\',
    b"{\\rtf1\\'xz}", b"{\\rtf1\\'0}", b'{\\rtf1\\bin-1 x}',
    b'{\\rtf1\\bin100 x}', b'{\\rtf1\\bin x}', b'{\\rtf1\\uc-1 x}',
    b'{\\rtf1\\u999999?}', b'{\\rtf1\\u?}', b'{\\rtf1\\ansicpg0 x}',
    b'{\\rtf1\\' + b'a' * 33 + b'}', b'{\\rtf1\\foo' + b'9' * 5000 + b'}'])
def test_malformed_is_parse_error(data):
    with pytest.raises(InvalidDocumentError) as exc:
        parse_rtf_bytes(data, Limits())
    assert isinstance(exc.value, ParseError)


def test_bom_and_whitespace():
    assert parse_rtf_bytes(b'\xef\xbb\xbf \r\n{\\rtf1 ok}\r\n ', Limits()).text == 'ok'


@pytest.mark.parametrize('body,limits', [
    ('x', {'max_file_bytes': 2}), ('x', {'max_stream_bytes': 2}),
    ('abcd', {'max_text_chars': 3}), ('{x}', {'max_depth': 1}),
    (r'\b\i\ul x', {'max_records': 4}),
    (r'{\*\unknown\b\i\ul x}', {'max_records': 5}),
    (r'\trowd\cell\cell\row', {'max_cells': 1}),
    (r'\trowd\cellx1\cellx2\row', {'max_cells': 1}),
    (r'A{\header BC}', {'max_text_chars': 2}),
    (r'{\header a}{\header b}', {'max_text_chars': 2}),
])
def test_limits(body, limits):
    with pytest.raises(LimitExceededError):
        parse(body, **limits)


def test_exact_text_limit_and_surrogate_budget():
    assert parse('abc', max_text_chars=3).text == 'abc'
    assert parse(r'\u-10179?\u-8704?', max_text_chars=1).text == '😀'
    assert parse(r"\ansicpg932\'82\'a0", max_text_chars=1).text == 'あ'


def test_skipped_text_does_not_consume_output_budget():
    assert parse(r'{\pict ' + '00' * 10000 + '}x', max_text_chars=2).text == 'x'


def test_metadata_destinations_and_skipped_font_changes():
    d = parse(r"\ansicpg1251{\info{\title private}{\author private}}"
              r"{\title private}{\*\unknown\ansicpg932{\fonttbl{\f0\cpg932 X;}}}"
              r"\'cf")
    assert d.text == 'П'


def test_hidden_and_deleted_are_independent():
    assert parse(r'\deleted\v0 secret\deleted0 visible').text == 'visible'
    assert parse(r'\v\deleted0 secret\v0 visible').text == 'visible'


def test_unicode_fallback_does_not_execute_destination_or_codepage():
    assert parse(r"\u945\pict X").text == 'αX'
    assert parse(r"\u945\ansicpg932\'e9").text == 'αé'


def test_low_text_limit_in_story_table_separators():
    with pytest.raises(LimitExceededError):
        parse(r'{\header\trowd a\cell b\cell\row}', max_text_chars=2)


def test_bounded_token_mutations_are_classified():
    import random
    rng = random.Random(142)
    units = [b'{', b'}', b'\\', b'\\bin0 ', b'\\bin3 ', b'\\u-10179?',
             b'\\u-8704?', b'\\uc2 ', b'\\trowd ', b'\\cell ', b'\\row ',
             b'\\fonttbl ', b'\\f1 ', b'\\cpg932 ', b'\\*', b'\\header ',
             b'\\footnote ', b'\\fldrslt ', b'\\pict ', b"\\'82", b'abc']
    limits = Limits(max_records=500, max_depth=20, max_text_chars=500, max_cells=50)
    for _ in range(1000):
        data = b'{\\rtf1 ' + b''.join(rng.choices(units, k=rng.randrange(50))) + b'}'
        try:
            document = parse_rtf_bytes(data, limits)
        except ParseError:
            continue
        document.text.encode('utf-8')  # No bare UTF-16 surrogates escape the API.
