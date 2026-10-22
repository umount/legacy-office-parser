"""Independent XML evidence for these small ORIGINAL fixtures; no production imports."""
from pathlib import Path
import xml.etree.ElementTree as ET
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


def docx_levels(path):
    """Only OOXML explicit outline and basedOn inheritance; no name heuristics."""
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

        result = {}
        for name in archive.namelist():
            if name != 'word/document.xml' and not (
                name.startswith('word/header') and name.endswith('.xml')
            ):
                continue
            for p in ET.fromstring(archive.read(name)).iter(f'{{{W}}}p'):
                text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
                if not text:
                    continue
                props = p.find('w:pPr', NS)
                own = outline(props)
                ref = None if props is None else props.find('w:pStyle', NS)
                value = (int(own.get(f'{{{W}}}val')) if own is not None else
                         inherited(None if ref is None else ref.get(f'{{{W}}}val')))
                assert text not in result
                assert value is None or 0 <= value <= 9
                result[text] = value + 1 if value is not None and value < 9 else None
        return result


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
