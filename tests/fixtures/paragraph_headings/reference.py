"""Independent XML evidence for these small ORIGINAL fixtures; no production imports."""
from pathlib import Path
import xml.etree.ElementTree as ET
import re
from zipfile import ZipFile

ROOT = Path(__file__).parent
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
T = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
S = 'urn:oasis:names:tc:opendocument:xmlns:style:1.0'
NS = {'w': W}
# Authored intent, never generated from a production parser or converter output.
EXPECTED = {
    'Heading one specimen': 1,
    'Heading two specimen': 2,
    'Ordinary body specimen': None,
    'Inherited heading specimen': 1,
    'Direct body override specimen': None,
    'Custom body style specimen': None,
    'Direct outline three specimen': 3,
    'Cell heading specimen': 2,
    'Header heading specimen': 2,
}
EXPLICIT = {**EXPECTED, 'Misleading style name specimen': None}
# LO 7.4.7.2 DOCX -> RTF drops ALL outline properties (including stylesheet).
RTF_EXPORT = {
    'Heading one specimen': None,
    'Heading two specimen': None,
    'Ordinary body specimen': None,
    'Inherited heading specimen': None,
    'Direct body override specimen': None,
    'Custom body style specimen': None,
    'Direct outline three specimen': None,
    'Cell heading specimen': None,
    'Header heading specimen': None,
}


def docx_evidence(path):
    """Fixture-only OOXML outlines and relationship-validated header variants."""
    with ZipFile(path) as archive:
        styles = {s.get(f'{{{W}}}styleId'): s
                  for s in ET.fromstring(archive.read('word/styles.xml'))}

        def outline(props):
            return None if props is None else props.find('w:outlineLvl', NS)

        def inherited(ident, seen=()):
            if ident is None:
                return None
            assert ident not in seen, 'cyclic fixture style'
            style = styles[ident]
            own = outline(style.find('w:pPr', NS))
            if own is not None:
                return int(own.get(f'{{{W}}}val'))
            base = style.find('w:basedOn', NS)
            return inherited(None if base is None else base.get(f'{{{W}}}val'), (*seen, ident))

        def paragraph(p):
            text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
            props = p.find('w:pPr', NS)
            own = outline(props)
            ref = None if props is None else props.find('w:pStyle', NS)
            value = (int(own.get(f'{{{W}}}val')) if own is not None else
                     inherited(None if ref is None else ref.get(f'{{{W}}}val')))
            assert value is None or 0 <= value <= 9
            return text, value + 1 if value is not None and value < 9 else None

        assert len(archive.namelist()) == len(set(archive.namelist())), 'duplicate ZIP part'
        document = ET.fromstring(archive.read('word/document.xml'))
        parents = {child: parent for parent in document.iter() for child in parent}
        body = document.find('w:body', NS)
        result = {}
        for p in document.iter(f'{{{W}}}p'):
            text, level = paragraph(p)
            if not text:
                continue
            assert text not in result, f'duplicate body/table paragraph: {text}'
            assert text != 'Header heading specimen', 'header text in body/table'
            if text == 'Cell heading specimen':
                assert parents[p].tag == f'{{{W}}}tc', 'cell heading outside table cell'
            else:
                assert parents[p] is body, f'body paragraph outside main body: {text}'
            result[text] = level

        # These authored specimens have one section. Validate references before
        # collapsing repeated header text; filenames alone do not prove ownership.
        sections = document.findall('.//w:sectPr', NS)
        assert len(sections) == 1, 'unexpected fixture section count'
        relns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        relations = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
        rels = {r.get('Id'): r for r in relations}
        assert len(rels) == len(relations), 'duplicate relationship ID'
        header_parts = {n for n in archive.namelist()
                        if re.fullmatch(r'word/header[^/]*\.xml', n)}
        used_parts, used_variants, headers = set(), set(), []
        canonical = None
        for ref in sections[0].findall('w:headerReference', NS):
            variant = ref.get(f'{{{W}}}type')
            assert variant in ('default', 'first', 'even'), 'invalid header variant'
            assert variant not in used_variants, 'duplicate header variant'
            used_variants.add(variant)
            rel = rels[ref.get(f'{{{relns}}}id')]
            assert rel.get('Type') == relns + '/header', 'wrong header relationship type'
            assert rel.get('TargetMode', 'Internal') == 'Internal', 'external header'
            target = rel.get('Target', '')
            assert re.fullmatch(r'header[^/]*\.xml', target), 'unexpected header target'
            name = 'word/' + target
            assert name in header_parts, 'missing header part'
            assert name not in used_parts, 'shared header target not in observed fixture profile'
            used_parts.add(name)
            header = ET.fromstring(archive.read(name))
            assert header.tag == f'{{{W}}}hdr', 'wrong header part root'
            header_parents = {c: parent for parent in header.iter() for c in parent}
            entries = []
            for p in header.iter(f'{{{W}}}p'):
                text, level = paragraph(p)
                if text:
                    assert header_parents[p] is header, 'header paragraph in nested container'
                    entries.append((text, level))
            if entries:
                assert len(entries) == 1, 'duplicate or extra paragraph within header part'
                assert entries[0][0] == 'Header heading specimen', 'unexpected header text'
                assert variant in ('default', 'first'), 'unobserved nonempty even header'
                if canonical is None:
                    canonical = entries
                assert entries == canonical, 'header copies disagree in text/heading'
            else:
                assert variant == 'even', 'non-even header unexpectedly empty'
            headers.append({'part': name, 'variant': variant, 'paragraphs': entries})
        assert used_parts == header_parts, 'unreferenced header part'
        assert any(h['variant'] == 'default' and h['paragraphs'] for h in headers), (
            'missing nonempty default header')
        assert canonical is not None
        result.update(canonical)
        return {'levels': result, 'headers': headers}


def docx_levels(path):
    """Independent levels, collapsing only validated copies of this fixture's header."""
    return docx_evidence(path)['levels']


def odt_evidence(path):
    """ODF heading elements are authoritative, including headings in master headers."""
    result, elements, styles = {}, {}, {}
    with ZipFile(path) as archive:
        for name in ('content.xml', 'styles.xml'):
            root = ET.fromstring(archive.read(name))
            for style in root.iter(f'{{{S}}}style'):
                styles[style.get(f'{{{S}}}name')] = dict(style.attrib)
            for p in root.iter():
                if p.tag not in (f'{{{T}}}p', f'{{{T}}}h'):
                    continue
                text = ''.join(p.itertext())
                if not text:
                    continue
                assert text not in result
                result[text] = int(p.get(f'{{{T}}}outline-level', '1')) if (
                    p.tag == f'{{{T}}}h') else None
                elements[text] = (p.tag, dict(p.attrib))
    return result, elements, styles
