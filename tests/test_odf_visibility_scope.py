"""Style ownership for sheet/slide hidden metadata, with original XML inputs."""
import pytest
from legacy_office_parser import parse
from test_odf import NS, package

DECL = ' '.join(f'xmlns:{key}="{value}"' for key, value in NS.items())


def style(fmt, name='S', hidden=True, parent=None):
    family, prop, attr = (('table', 'table-properties', 'table:display') if fmt == 'ods'
                          else ('drawing-page', 'drawing-page-properties', 'presentation:visibility'))
    value = ('false' if hidden else 'true') if fmt == 'ods' else ('hidden' if hidden else 'visible')
    parent_attr = '' if parent is None else f' style:parent-style-name="{parent}"'
    return (f'<style:style style:name="{name}" style:family="{family}"{parent_attr}>'
            f'<style:{prop} {attr}="{value}"/></style:style>')


def document(fmt, host_styles, embedded_styles='', *, extra_styles='', unstyled=False):
    embedded = ('<draw:frame><draw:object><office:document office:version="1.3" '
                'office:mimetype="application/vnd.oasis.opendocument.text">'
                f'<office:automatic-styles>{embedded_styles}</office:automatic-styles>'
                '<office:body><office:text><text:p>Embedded</text:p></office:text></office:body>'
                '</office:document></draw:object></draw:frame>') if embedded_styles else ''
    if fmt == 'ods':
        body = ('<table:table table:name="Sheet" table:style-name="S"><table:shapes>' + embedded +
                '</table:shapes><table:table-row><table:table-cell><text:p>Host</text:p>'
                '</table:table-cell></table:table-row></table:table>')
        kind = 'spreadsheet'
    else:
        body = ('<draw:page draw:style-name="S"><draw:frame><draw:text-box><text:p>Host</text:p>'
                '</draw:text-box></draw:frame>' + embedded + '</draw:page>')
        kind = 'presentation'
    if unstyled:
        body = body.replace(' table:style-name="S"', '').replace(' draw:style-name="S"', '')
    content = (f'<office:document-content {DECL}><office:automatic-styles>{host_styles}'
               f'</office:automatic-styles><office:body><office:{kind}>{body}'
               f'</office:{kind}></office:body></office:document-content>')
    extra = {'styles.xml': f'<office:document-styles {DECL}>{extra_styles}</office:document-styles>'} if extra_styles else None
    return parse(package(fmt=fmt, content=content, extra=extra))


def hidden(doc):
    return (doc.sheets or doc.slides)[0].hidden


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
@pytest.mark.parametrize('host_hidden', [False, True])
def test_embedded_style_cannot_override_host_flag(fmt, host_hidden):
    doc = document(fmt, style(fmt, hidden=host_hidden), style(fmt, hidden=not host_hidden))
    assert hidden(doc) is host_hidden
    assert 'Host' in doc.text
    assert 'Embedded' not in doc.text


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_embedded_only_style_cannot_hide_host(fmt):
    assert hidden(document(fmt, '', style(fmt))) is False


def reference(fmt, name='S', parent='Base'):
    family = 'table' if fmt == 'ods' else 'drawing-page'
    return (f'<style:style style:name="{name}" style:family="{family}" '
            f'style:parent-style-name="{parent}"/>')


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_other_xml_automatic_styles_do_not_supply_body_style(fmt):
    other = '<office:automatic-styles>' + style(fmt) + '</office:automatic-styles>'
    assert hidden(document(fmt, '', extra_styles=other)) is False


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_common_parent_with_same_name_is_not_auto_self_cycle(fmt):
    common = '<office:styles>' + style(fmt) + '</office:styles>'
    assert hidden(document(fmt, reference(fmt, parent='S'), extra_styles=common)) is True


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_automatic_parent_reference_resolves_common_not_another_auto(fmt):
    automatic = reference(fmt) + style(fmt, 'Base', hidden=False)
    common = '<office:styles>' + style(fmt, 'Base') + '</office:styles>'
    assert hidden(document(fmt, automatic, extra_styles=common)) is True


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_missing_common_parent_cannot_be_supplied_by_auto(fmt):
    doc = document(fmt, reference(fmt) + style(fmt, 'Base'))
    assert hidden(doc) is False
    assert any(d.code == 'odf_sheet_slide_visibility_style_unresolved' for d in doc.diagnostics)


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
@pytest.mark.parametrize('reverse', [False, True])
def test_duplicate_automatic_style_cannot_take_last_hidden_value(fmt, reverse):
    entries = [style(fmt), style(fmt, hidden=False)]
    doc = document(fmt, ''.join(reversed(entries) if reverse else entries))
    assert hidden(doc) is False
    assert any(d.code == 'odf_sheet_slide_visibility_style_unresolved' for d in doc.diagnostics)


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_common_parent_cycle_and_missing_name_are_bounded(fmt):
    common = ('<office:styles>' + reference(fmt, 'Base', 'Other') +
              reference(fmt, 'Other', 'Base') + '</office:styles>')
    assert hidden(document(fmt, reference(fmt), extra_styles=common)) is False
    assert hidden(document(fmt, reference(fmt))) is False


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_direct_visible_property_overrides_hidden_parent(fmt):
    common = '<office:styles>' + style(fmt, 'Base') + '</office:styles>'
    assert hidden(document(fmt, style(fmt, hidden=False, parent='Base'), extra_styles=common)) is False


def default_style(fmt, hidden=True):
    return style(fmt, hidden=hidden).replace('style:style', 'style:default-style').replace(' style:name="S"', '')


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_resolved_style_without_parent_uses_own_family_default(fmt):
    family = 'table' if fmt == 'ods' else 'drawing-page'
    leaf = f'<style:style style:name="S" style:family="{family}"/>'
    common = '<office:styles>' + default_style(fmt) + '</office:styles>'
    assert hidden(document(fmt, leaf, extra_styles=common)) is True
    assert hidden(document(fmt, style(fmt, hidden=False), extra_styles=common)) is False


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_missing_parent_does_not_fall_through_to_default(fmt):
    common = '<office:styles>' + default_style(fmt) + '</office:styles>'
    assert hidden(document(fmt, reference(fmt), extra_styles=common)) is False


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_duplicate_default_does_not_choose_last(fmt):
    family = 'table' if fmt == 'ods' else 'drawing-page'
    leaf = f'<style:style style:name="S" style:family="{family}"/>'
    common = '<office:styles>' + default_style(fmt, False) + default_style(fmt) + '</office:styles>'
    doc = document(fmt, leaf, extra_styles=common)
    assert hidden(doc) is False
    assert any(d.code == 'odf_sheet_slide_visibility_style_unresolved' for d in doc.diagnostics)


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_unstyled_element_uses_family_default_and_retains_content(fmt):
    common = '<office:styles>' + default_style(fmt) + '</office:styles>'
    doc = document(fmt, '', extra_styles=common, unstyled=True)
    assert hidden(doc) is True
    assert 'Host' in doc.text
    wrong = default_style('odp' if fmt == 'ods' else 'ods')
    assert hidden(document(fmt, '', extra_styles='<office:styles>' + wrong + '</office:styles>',
                           unstyled=True)) is False


@pytest.mark.parametrize('fmt', ['ods', 'odp'])
def test_embedded_default_cannot_supply_host_default(fmt):
    embedded = ('</office:automatic-styles><office:styles>' + default_style(fmt) +
                '</office:styles><office:automatic-styles>')
    assert hidden(document(fmt, '', embedded, unstyled=True)) is False
