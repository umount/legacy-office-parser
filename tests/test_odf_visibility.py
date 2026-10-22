"""Original synthetic visibility cases; no external documents or expression runtime.

ODF 1.3 Part 3 §§7.7.11, 16.2, 19.510, 19.821, 20.427:
https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html
"""
import json

import pytest

from legacy_office_parser import Limits, LimitExceededError, parse, parse_odt
from test_odf import NS, package
from test_odf_stories import frame, master, note, styles, table
from test_odf_story_blocks import document, KEYS


def p(text='', style=None, tag='p'):
    attr = '' if style is None else f' text:style-name="{style}"'
    return f'<text:{tag}{attr}>{text}</text:{tag}>'


def marker(state='true', condition='secret-expression'):
    attr = '' if state is None else f' text:is-hidden="{state}"'
    return f'<text:hidden-paragraph text:condition="{condition}"{attr}/>'


def style(name, family='paragraph', display=None, parent=None, extra=''):
    attr = '' if parent is None else f' style:parent-style-name="{parent}"'
    prop = '' if display is None else f'<style:text-properties text:display="{display}"/>'
    return (f'<style:style style:name="{name}" style:family="{family}"{attr}>'
            f'{prop}{extra}</style:style>')


def packaged(body, fmt='odt', common='', automatic='', styles_auto='', masters=''):
    if fmt == 'ods':
        body = table(body)
    elif fmt == 'odp':
        body = '<draw:page>' + frame(body) + '</draw:page>'
    namespaces = ' '.join(f'xmlns:{name}="{uri}"' for name, uri in NS.items())
    family = {'odt': 'text', 'ods': 'spreadsheet', 'odp': 'presentation'}[fmt]
    content = (f'<office:document-content {namespaces}>'
               f'<office:automatic-styles>{automatic}</office:automatic-styles>'
               f'<office:body><office:{family}>{body}</office:{family}>'
               '</office:body></office:document-content>')
    return package(fmt=fmt, content=content,
                   extra={'styles.xml': styles(masters, common, styles_auto)})


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
@pytest.mark.parametrize('state', ['true', '1', ' true&#x9;'])
@pytest.mark.parametrize('tag', ['p', 'h'])
def test_explicit_hidden_paragraph_preflight_before_text_or_stories(fmt, state, tag):
    secret = 'secret-text' + frame(p('secret-frame')) + note(p('secret-note'))
    body = p('before') + p(secret + '<text:span>' + marker(state) + '</text:span>', tag=tag) + p('after')
    doc = parse(packaged(body, fmt))
    assert 'secret' not in doc.text
    assert doc.footnotes == doc.textboxes == ''
    assert 'before' in doc.text and 'after' in doc.text
    assert sum('hidden paragraph omitted' in w for w in doc.warnings) == 1
    assert 'secret' not in '\n'.join(doc.warnings)
    if fmt == 'odt':
        assert [b.text for b in doc.blocks] == ['before', 'after']


@pytest.mark.parametrize('state', ['false', '0', None, 'invalid'])
def test_visible_or_unknown_state_never_evaluates_condition(state):
    doc = parse(packaged(p('visible' + marker(state, 'true()'))))
    assert doc.text == 'visible'
    assert bool(doc.warnings) == (state in (None, 'invalid'))


@pytest.mark.parametrize('reverse', [False, True])
def test_visible_marker_overrides_hidden_marker_in_same_paragraph(reverse):
    controls = [marker('true'), '<text:a>' + marker('false') + '</text:a>']
    if reverse:
        controls.reverse()
    assert parse(packaged(p('visible' + ''.join(controls)))).text == 'visible'


@pytest.mark.parametrize('wrap,key', [(frame, 'textboxes'), (note, 'footnotes')])
def test_inner_paragraph_visibility_does_not_hide_host(wrap, key):
    doc = parse(packaged(p('host' + wrap(p('inner-secret' + marker())))))
    assert doc.text == 'host'
    assert getattr(doc, key) == ''


@pytest.mark.parametrize('key', KEYS)
def test_hidden_paragraphs_in_pooled_stories(key):
    doc = parse_odt(document(key, [p('before'), p('secret' + marker()), p('after')]))
    assert getattr(doc, key) == 'before\n\nafter'
    assert 'secret' not in json.dumps(doc.to_dict())


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_hidden_sections_suppress_all_descendants_and_leave_inserted_text(fmt):
    deleted = ('<text:tracked-changes><text:changed-region text:id="d"><text:deletion>' +
               p('deleted-secret' + frame(p('deleted-frame'))) +
               '</text:deletion></text:changed-region></text:tracked-changes>')
    hidden = ('<text:section text:display="none">' + p('hidden-secret') +
              table(p(frame(p('hidden-frame')) + note(p('hidden-note')))) + '</text:section>')
    inserted = p('A<text:change-start text:change-id="i"/>inserted'
                 '<text:change-end text:change-id="i"/>B<text:change text:change-id="d"/>')
    doc = parse(packaged(deleted + hidden + inserted, fmt))
    assert 'AinsertedB' in doc.text
    assert all(s not in doc.text for s in ('deleted', 'hidden'))
    assert doc.textboxes == doc.footnotes == ''


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_condition_section_not_evaluated(fmt):
    doc = parse(packaged('<text:section text:display="condition" text:condition="true()">' +
                        p('retained') + '</text:section>', fmt))
    assert 'retained' in doc.text
    assert any('conditional section' in w for w in doc.warnings)


@pytest.mark.parametrize('fmt', ['odt', 'ods', 'odp'])
def test_inherited_paragraph_and_text_styles_with_visible_override(fmt):
    common = (style('PBase', display='none') + style('PChild', parent='PBase') +
              style('TBase', 'text', 'none') + style('TChild', 'text', parent='TBase') +
              style('Show', 'text', 'true'))
    body = (p('secret' + frame(p('secret-frame')) + note(p('secret-note')) +
              '<text:span text:style-name="Show">shown</text:span>secret', 'PChild') +
            p('A<text:span text:style-name="TChild">secret' + frame(p('secret-frame')) +
              '</text:span>B'))
    doc = parse(packaged(body, fmt, common))
    assert 'shown' in doc.text and 'AB' in doc.text
    assert 'secret' not in doc.text
    assert doc.textboxes == doc.footnotes == ''
    assert sum('hidden styled text' in w for w in doc.warnings) == 1


def test_nearest_property_and_family_matching_and_paragraph_default():
    default = ('<style:default-style style:family="paragraph">'
               '<style:text-properties text:display="none"/></style:default-style>')
    common = (default + style('Base', display='none') + style('Show', display='true', parent='Base') +
              style('Show', 'text', 'none'))
    doc = parse(packaged(p('secret') + p('visible', 'Show'), common=common))
    assert doc.text == 'visible'


def test_automatic_styles_are_file_scoped_and_parents_are_common():
    common = style('Base', display='none') + style('Main', display='true')
    automatic = style('Main', parent='Base') + style('Base', display='true')
    styles_auto = style('Main', display='true')
    doc = parse(packaged(p('secret-body', 'Main'), common=common, automatic=automatic,
                        styles_auto=styles_auto,
                        masters=master('<style:header>' + p('visible-header', 'Main') + '</style:header>')))
    assert doc.text == 'visible-header'


def test_embedded_document_style_scope_cannot_hide_host_or_inherit_host():
    embedded = ('<draw:frame><draw:object><office:document '
                'office:mimetype="application/vnd.oasis.opendocument.text">'
                '<office:styles>' + style('Inner', display='none') + '</office:styles>'
                '<office:body><office:text>' + p('secret-inner', 'Inner') + p('visible-inner', 'Host') +
                '</office:text></office:body></office:document></draw:object></draw:frame>')
    doc = parse(packaged(p('visible-host', 'Inner') + p('secret-host', 'Host') + embedded,
                        common=style('Host', display='none')))
    assert doc.text == 'visible-host\n\nvisible-inner'
    assert doc.textboxes == 'visible-inner'


@pytest.mark.parametrize('display', ['condition', 'false', 'invalid'])
def test_unsupported_style_display_does_not_evaluate_or_inherit_hidden_parent(display):
    common = style('Base', display='none') + style('Child', display=display, parent='Base')
    doc = parse(packaged(p('visible', 'Child'), common=common))
    assert doc.text == 'visible'
    assert any('visibility is not evaluated' in w for w in doc.warnings)


def test_style_map_never_evaluated():
    common = style('Hidden', display='none') + style('P', extra=(
        '<style:map style:condition="true()" style:apply-style-name="Hidden"/>'))
    doc = parse(packaged(p('visible', 'P'), common=common))
    assert doc.text == 'visible'
    assert any('conditional text styles' in w for w in doc.warnings)


@pytest.mark.parametrize('common', [style('A', parent='B') + style('B', parent='A'),
                                    style('A', display='none') + style('A', display='true'),
                                    style('A', parent='Missing')])
def test_ambiguous_styles_terminate_with_non_source_bearing_warning(common):
    doc = parse(packaged(p('visible', 'A'), common=common))
    assert doc.text == 'visible'
    assert doc.warnings
    assert 'Missing' not in '\n'.join(doc.warnings)


def test_cycle_with_proven_hidden_property_does_not_reveal_text():
    common = style('A', display='none', parent='B') + style('B', parent='A')
    doc = parse(packaged(p('secret', 'A'), common=common))
    assert doc.text == ''
    assert any('cyclic' in w for w in doc.warnings)


def test_style_depth_limit_even_for_non_nested_xml():
    common = ''.join(style(f'S{i}', parent=f'S{i+1}') for i in range(12)) + style('S12')
    with pytest.raises(LimitExceededError, match='style inheritance depth'):
        parse(packaged(p('text', 'S0'), common=common), limits=Limits(max_depth=8))


@pytest.mark.parametrize('hide', ['marker', 'style', 'section'])
def test_hidden_expansion_is_not_rendered_but_source_budgets_still_apply(hide):
    huge = '<text:s text:c="999999999999999999999"/>'
    body = p(huge + marker()) if hide == 'marker' else (
        p(huge, 'Hidden') if hide == 'style' else
        '<text:section text:display="none">' + p(huge) + '</text:section>')
    data = packaged(body + p('ok'), common=style('Hidden', display='none'))
    assert parse(data, limits=Limits(max_text_chars=2000)).text == 'ok'
    with pytest.raises(LimitExceededError):
        parse(data, limits=Limits(max_records=3))
    with pytest.raises(LimitExceededError):
        parse(data, limits=Limits(max_text_chars=50))
    with pytest.raises(LimitExceededError):
        parse(packaged(p(huge)))


def test_visible_repeat_budget_and_detached_story_ownership():
    data = packaged(table(p('secret' + frame(p('secret-story')) + marker()) +
                          p('<text:s text:c="1000"/>'), rows=2, columns=3))
    assert parse(data, limits=Limits(max_text_chars=6005)).text.count(' ') == 6000
    with pytest.raises(LimitExceededError):
        parse(data, limits=Limits(max_text_chars=6004))
    with pytest.raises(LimitExceededError):
        parse(data, limits=Limits(max_cells=5))


def test_ods_cached_value_does_not_resurrect_hidden_display():
    body = ('<table:table><table:table-row><table:table-cell office:value-type="string" '
            'office:string-value="secret-cache">' + p('secret-display' + marker()) +
            '</table:table-cell></table:table-row></table:table>')
    doc = parse(package(body, 'ods'))
    cell = doc.sheets[0].cells[0]
    assert cell.value == 'secret-cache'  # Typed cached data is not a redaction API.
    assert cell.text == ''
    assert 'secret' not in doc.text


def test_ods_floating_labels_use_same_paragraph_filter():
    body = ('<table:table table:name="S"><table:shapes>' + frame(
        p('secret' + marker()) + p('visible')) + '</table:shapes></table:table>')
    doc = parse(package(body, 'ods'))
    assert doc.sheets[0].drawings == ['visible']


def test_omitted_scopes_do_not_influence_host_paragraph_markers():
    ignored = ('<office:annotation>' + p(marker()) + '</office:annotation>' +
               '<text:tracked-changes><text:changed-region text:id="d"><text:deletion>' +
               p(marker()) + '</text:deletion></text:changed-region></text:tracked-changes>')
    assert parse(packaged(p('visible' + ignored))).text == 'visible'


def test_default_text_style_and_explicit_paragraph_visibility():
    default = ('<style:default-style style:family="text">'
               '<style:text-properties text:display="none"/></style:default-style>')
    common = default + style('Visible', display='true')
    body = p('A<text:span>secret</text:span>B') + p('<text:span>visible</text:span>', 'Visible')
    doc = parse(packaged(body, common=common))
    assert doc.text == 'AB\n\nvisible'


def test_text_visibility_overrides_restore_after_nested_spans():
    common = style('Hide', 'text', 'none') + style('Show', 'text', 'true')
    body = p('A<text:span text:style-name="Hide">secret'
             '<text:span text:style-name="Show">B</text:span>secret</text:span>C')
    assert parse(packaged(body, common=common)).text == 'ABC'


def test_ruby_base_marker_hides_paragraph_but_annotation_does_not():
    body = p('secret<text:ruby><text:ruby-base>' + marker() +
             '</text:ruby-base><text:ruby-text>annotation</text:ruby-text></text:ruby>')
    body += p('visible<text:ruby><text:ruby-base>base</text:ruby-base>'
              '<text:ruby-text>' + marker() + '</text:ruby-text></text:ruby>')
    assert parse(packaged(body)).text == 'visiblebase'


def test_hidden_heading_does_not_opt_in_cell_structure_or_emit_bad_level_warning():
    body = table('<text:h text:outline-level="source-secret">secret' + marker() + '</text:h>' + p('visible'))
    doc = parse(packaged(body))
    assert doc.blocks[0].rows[0][0].blocks == []
    assert doc.text == 'visible'
    assert not any('heading level' in w for w in doc.warnings)


@pytest.mark.parametrize('body,common', [
    ('<text:section text:display="none">' + p('secret') + '</text:section>', ''),
    (p('secret', 'Hidden'), style('Hidden', display='none')),
    (p('<text:span text:style-name="Hidden">secret</text:span>'), style('Hidden', 'text', 'none')),
])
def test_ods_all_hidden_display_paths_block_cached_display_fallback(body, common):
    namespaces = ' '.join(f'xmlns:{name}="{uri}"' for name, uri in NS.items())
    content = (f'<office:document-content {namespaces}><office:body><office:spreadsheet>'
               '<table:table><table:table-row><table:table-cell office:value-type="string" '
               'office:string-value="secret-cache">' + body +
               '</table:table-cell></table:table-row></table:table>'
               '</office:spreadsheet></office:body></office:document-content>')
    doc = parse(package(fmt='ods', content=content, extra={'styles.xml': styles('', common)}))
    assert doc.sheets[0].cells[0].text == ''
    assert doc.sheets[0].cells[0].value == 'secret-cache'
    assert 'secret' not in doc.text


def test_visible_master_is_not_selected_by_hidden_paragraph_or_hidden_soft_break():
    common = (style('HiddenPage', extra='<style:paragraph-properties/>')
              .replace('style:family="paragraph"',
                       'style:family="paragraph" style:master-page-name="Other"') +
              style('HiddenSpan', 'text', 'none'))
    masters = (master('<style:header>' + p('first') + '</style:header>')
               .replace('style:name="Standard"', 'style:name="Standard" style:next-style-name="Other"') +
               master('<style:header>' + p('secret-header') + '</style:header>', 'Other'))
    body = p('secret' + marker(), 'HiddenPage') + p('visible<text:span text:style-name="HiddenSpan">'
                                                '<text:soft-page-break/></text:span>')
    doc = parse(packaged(body, common=common, masters=masters))
    assert doc.headers_footers == 'first'
    assert 'secret' not in doc.text
