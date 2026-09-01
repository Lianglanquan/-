from __future__ import annotations

from pathlib import Path
import io
import unittest
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/derived/厚璨杯分区赛_完整补充稿.docx"
NS = {
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}


class ReportImageGeometryTests(unittest.TestCase):
    def test_report_images_have_explicit_locked_aspect_geometry(self) -> None:
        with ZipFile(REPORT) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            media = {
                name.rsplit("/", 1)[-1]: archive.read(name)
                for name in archive.namelist()
                if name.startswith("word/media/") and name.lower().endswith((".png", ".jpg", ".jpeg"))
            }

            inlines = document.findall(".//wp:inline", NS)
            extents = [inline.find("./wp:extent", NS) for inline in inlines]
            shapes = document.findall(".//pic:pic", NS)
            self.assertTrue(extents, "the report should contain embedded figures")
            self.assertEqual(len(extents), len(shapes))

            for inline, extent, shape in zip(inlines, extents, shapes):
                self.assertIsNotNone(extent)
                cx = int(extent.attrib["cx"])
                cy = int(extent.attrib["cy"])
                self.assertGreater(cx, 0)
                self.assertGreater(cy, 0)

                shape_extent = shape.find("./pic:spPr/a:xfrm/a:ext", NS)
                self.assertIsNotNone(shape_extent)
                self.assertEqual(shape_extent.attrib, {"cx": str(cx), "cy": str(cy)})

                frame_locks = inline.find("./wp:cNvGraphicFramePr/a:graphicFrameLocks", NS)
                self.assertIsNotNone(frame_locks)
                self.assertEqual(frame_locks.attrib.get("noChangeAspect"), "1")

                use_local_dpi = shape.find("./pic:blipFill/a:blip/a:extLst/a:ext/a14:useLocalDpi", NS)
                self.assertIsNotNone(use_local_dpi)
                self.assertEqual(use_local_dpi.attrib.get("val"), "0")

                image_name = shape.find("./pic:nvPicPr/pic:cNvPr", NS).attrib["name"]
                if image_name in media:
                    with Image.open(io.BytesIO(media[image_name])) as image:
                        source_ratio = image.width / image.height
                    self.assertLess(abs((cx / cy) - source_ratio), 0.002)


if __name__ == "__main__":
    unittest.main()
