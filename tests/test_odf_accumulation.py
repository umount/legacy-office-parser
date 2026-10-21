"""Incremental text and style traversal limits with small authored packages."""
import pytest

from legacy_office_parser import parse, Limits, LimitExceededError
from legacy_office_parser.odf import _Parser
from test_odf import package, NS


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_cell_stops_before_accumulating_all_paragraphs(fmt, monkeypatch):
    body = ('<table:table><table:table-row><table:table-cell>' +
            '<text:p><text:s text:c="3000"/></text:p>' * 20 +
            '</table:table-cell></table:table-row></table:table>')
    if fmt == 'odp':
        body = '<draw:page>' + body + '</draw:page>'
    original = _Parser.inline
    calls = []

    def counted(self, element):
        calls.append(1)
        return original(self, element)

    monkeypatch.setattr(_Parser, 'inline', counted)
    with pytest.raises(LimitExceededError):
        parse(package(body, fmt), limits=Limits(max_text_chars=10000))
    assert len(calls) == 4  # Reject the first excess paragraph, not the final join.


def presentation_styles(count):
    styles = ''.join('<style:style style:family="drawing-page" style:name="s%d" '
                     'style:parent-style-name="s%d"/>' % (i, i + 1)
                     for i in range(count))
    declarations = ' '.join(f'xmlns:{p}="{uri}"' for p, uri in NS.items())
    return package(fmt='odp', content=f'<office:document-content {declarations}>'
                   '<office:automatic-styles>' + styles + '</office:automatic-styles>'
                   '<office:body><office:presentation><draw:page draw:style-name="s0"/>'
                   '</office:presentation></office:body></office:document-content>')


def test_slide_style_inheritance_obeys_depth_budget():
    with pytest.raises(LimitExceededError, match='style inheritance'):
        parse(presentation_styles(20), limits=Limits(max_depth=8))


def test_short_missing_parent_style_keeps_existing_fallback():
    assert not parse(presentation_styles(3)).slides[0].hidden


def test_missing_parent_at_exact_depth_keeps_fallback():
    assert not parse(presentation_styles(8), limits=Limits(max_depth=8)).slides[0].hidden
