import json
import os
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.document.MacroExecMode import NEVER_EXECUTE
from com.sun.star.document.UpdateDocMode import NO_UPDATE

ROOT = Path(__file__).parent


def prop(name, value):
    p = PropertyValue()
    p.Name = name
    p.Value = value
    return p


def writer(model):
    if model is None:
        return {"model": None}
    result = {"writer_service": model.supportsService("com.sun.star.text.TextDocument")}
    if result["writer_service"]:
        result["text"] = model.Text.String
        result["table_count"] = model.TextTables.Count
        result["cell_A1"] = model.TextTables.getByName("Inner").getCellByName("A1").String
    return result


with tempfile.TemporaryDirectory(prefix="odp-uno-", dir=ROOT) as profile:
    pipe = "odp" + uuid.uuid4().hex
    process = subprocess.Popen(
        [
            "/usr/bin/libreoffice",
            "-env:UserInstallation=" + Path(profile).as_uri(),
            "--headless",
            "--norestore",
            "--nodefault",
            "--nofirststartwizard",
            "--accept=pipe,name=" + pipe + ";urp;StarOffice.ComponentContext",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local
        )
        for _ in range(100):
            try:
                ctx = resolver.resolve("uno:pipe,name=" + pipe + ";urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("UNO connection timeout")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        for ext in ("odp", "odt"):
            doc = desktop.loadComponentFromURL(
                (ROOT / ("inline." + ext)).as_uri(),
                "_blank",
                0,
                tuple(
                    prop(k, v)
                    for k, v in [
                        ("Hidden", True),
                        ("ReadOnly", True),
                        ("MacroExecutionMode", NEVER_EXECUTE),
                        ("UpdateDocMode", NO_UPDATE),
                    ]
                ),
            )
            result = {"format": ext, "loaded": doc is not None}
            if doc is not None:
                if ext == "odp":
                    result["page_count"] = doc.DrawPages.Count
                    pages = []
                    for i in range(doc.DrawPages.Count):
                        page = doc.DrawPages.getByIndex(i)
                        shapes = []
                        for j in range(page.Count):
                            shape = page.getByIndex(j)
                            info = {"type": shape.ShapeType}
                            if shape.getPropertySetInfo().hasPropertyByName("Model"):
                                info["embedded"] = writer(shape.Model)
                            else:
                                info["model_property"] = False
                            shapes.append(info)
                        pages.append({"shape_count": page.Count, "shapes": shapes})
                    result["pages"] = pages
                else:
                    result["embedded_count"] = doc.EmbeddedObjects.Count
                    result["embedded"] = [
                        writer(doc.EmbeddedObjects.getByIndex(i).Model)
                        for i in range(doc.EmbeddedObjects.Count)
                    ]
                doc.close(True)
            print(json.dumps(result), flush=True)
        desktop.terminate()
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
