"""Authored numeric-free comments; run with /usr/bin/python3 (UNO installed).

Usage: generate.py OUTPUT_DIRECTORY [--read EXISTING_PPT]
Read mode never saves the input. Output metadata is independent UNO readback.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import uno

COMMENTS = [
    [('Research Author', 'RA', 'Budget excludes migration'),
     ('Review Author', 'RV', 'Привет — проверить\nSecond comment line')],
    [('Research Author', 'RA', 'Slide body 2')],
]


def props(**kwargs):
    values = []
    for key, value in kwargs.items():
        prop = uno.createUnoStruct('com.sun.star.beans.PropertyValue')
        prop.Name, prop.Value = key, value
        values.append(prop)
    return tuple(values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--read', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ppt-comments-uno-') as profile:
        pipe = 'comments_' + uuid.uuid4().hex
        proc = subprocess.Popen(['/usr/bin/libreoffice', '-env:UserInstallation=' + Path(profile).as_uri(),
                                 '--headless', '--norestore', '--nodefault', '--nofirststartwizard',
                                 '--accept=pipe,name=' + pipe + ';urp;StarOffice.ComponentContext'],
                                env={**os.environ, 'SAL_USE_VCLPLUGIN': 'svp', 'GSETTINGS_BACKEND': 'memory'},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        doc = None
        try:
            local = uno.getComponentContext()
            resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
            deadline = time.monotonic() + 15
            while True:
                try:
                    ctx = resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
                    break
                except Exception:
                    if proc.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('isolated LibreOffice startup failed')
                    time.sleep(.1)
            desktop = ctx.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', ctx)
            safe = dict(Hidden=True, MacroExecutionMode=uno.getConstantByName('com.sun.star.document.MacroExecMode.NEVER_EXECUTE'), UpdateDocMode=0)
            path = args.read.resolve() if args.read else (args.output / 'comments.ppt').resolve()
            if not args.read:
                doc = desktop.loadComponentFromURL('private:factory/simpress', '_blank', 0, props(**safe))
                pages = doc.getDrawPages()
                pages.insertNewByIndex(1)
                for index in range(2):
                    page = pages.getByIndex(index)
                    while page.getCount():
                        page.remove(page.getByIndex(0))
                    page.Layout = 20
                    page.IsFooterVisible = page.IsDateTimeVisible = page.IsPageNumberVisible = False
                    shape = doc.createInstance('com.sun.star.drawing.TextShape')
                    shape.Position = uno.createUnoStruct('com.sun.star.awt.Point', 1500, 2500)
                    shape.Size = uno.createUnoStruct('com.sun.star.awt.Size', 22000, 1800)
                    page.add(shape)
                    shape.String = 'Slide body ' + str(index + 1)
                    for author, initials, text in COMMENTS[index]:
                        annotation = page.createAndInsertAnnotation()
                        annotation.Author, annotation.Initials = author, initials
                        annotation.TextRange.String = text
                        annotation.Position = uno.createUnoStruct('com.sun.star.geometry.RealPoint2D', 20.0, 30.0)
                doc.storeAsURL(path.as_uri(), props(FilterName='MS PowerPoint 97', Overwrite=True))
                doc.close(True)
                doc = None
            before = path.read_bytes()
            doc = desktop.loadComponentFromURL(path.as_uri(), '_blank', 0, props(ReadOnly=True, **safe))
            assert doc is not None
            output = []
            for index in range(doc.getDrawPages().getCount()):
                page = doc.getDrawPages().getByIndex(index)
                comments = []
                enum = page.createAnnotationEnumeration()
                while enum.hasMoreElements():
                    item = enum.nextElement()
                    comments.append(dict(author=item.Author, initials=item.Initials, text=item.TextRange.String))
                body = [page.getByIndex(i).String for i in range(page.getCount())
                        if hasattr(page.getByIndex(i), 'String')]
                output.append(dict(slide=index + 1, body=body, comments=comments))
            doc.close(True)
            doc = None
            assert path.read_bytes() == before
            (args.output / 'uno-readback.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(output, ensure_ascii=False))
        finally:
            if doc is not None:
                doc.close(True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == '__main__':
    main()
