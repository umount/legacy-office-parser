from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

ROOT = Path(__file__).parent
NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
}
DECL = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())
BODY = (
    '<text:p>Object before</text:p><table:table table:name="Inner"><table:table-column/>'
    '<table:table-row><table:table-cell office:value-type="string"><text:p>Object cell</text:p>'
    "</table:table-cell></table:table-row></table:table><text:p>Object after</text:p>"
)
OBJ = (
    '<draw:object><office:document office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.text">'
    "<office:body><office:text>"
    + BODY
    + "</office:text></office:body></office:document></draw:object>"
)
for ext, kind in [("odp", "presentation"), ("odt", "text")]:
    frame = (
        '<draw:frame draw:name="InlineWriter" svg:x="1cm" svg:y="1cm" svg:width="8cm" svg:height="4cm"'
        + (' text:anchor-type="as-char"' if ext == "odt" else "")
        + ">"
        + OBJ
        + "</draw:frame>"
    )
    body = (
        '<draw:page draw:name="Page1" draw:master-page-name="Default">' + frame + "</draw:page>"
        if ext == "odp"
        else "<text:p>Host before" + frame + "Host after</text:p>"
    )
    content = (
        f'<office:document-content {DECL} office:version="1.3"><office:body><office:{kind}>'
        + body
        + f"</office:{kind}></office:body></office:document-content>"
    )
    styles = (
        f'<office:document-styles {DECL} office:version="1.3"><office:automatic-styles>'
        '<style:page-layout style:name="PageLayout"><style:page-layout-properties fo:page-width="28cm" fo:page-height="21cm" style:print-orientation="landscape"/>'
        '</style:page-layout></office:automatic-styles><office:master-styles><style:master-page style:name="Default" style:page-layout-name="PageLayout"/>'
        "</office:master-styles></office:document-styles>"
    )
    mime = "application/vnd.oasis.opendocument." + kind
    manifest = (
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
        f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/></manifest:manifest>'
    )
    with ZipFile(ROOT / ("inline." + ext), "w", ZIP_STORED) as z:
        for name, value in [
            ("mimetype", mime),
            ("content.xml", content),
            ("styles.xml", styles),
            ("META-INF/manifest.xml", manifest),
        ]:
            z.writestr(name, value)
    for name, value in [("content", content), ("styles", styles), ("manifest", manifest)]:
        (ROOT / (ext + "-" + name + ".xml")).write_text(value)
print("Original ODP and matching ODT control created.")
