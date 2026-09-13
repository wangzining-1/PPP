"""Native exporter integration; needs the local configured Codex runtime."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / 'ppp/runtime.local.json').exists(), 'Requires local Codex runtime configuration')
class MechanismExportTests(unittest.TestCase):
    def test_native_no_background_no_media_and_inhibition_bar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = subprocess.run([sys.executable, str(ROOT/'ppp/scripts/run.py'), 'mechanism',
                str(ROOT/'examples/feedback.mechanism.json'), str(root/'cache')], check=True, capture_output=True, text=True)
            scene = json.loads(result.stdout)['scene']
            subprocess.run([sys.executable, str(ROOT/'ppp/scripts/run.py'), 'export', scene,
                str(root/'sample.pptx'), str(root/'sample.svg')], check=True, capture_output=True, text=True)
            with zipfile.ZipFile(root/'sample.pptx') as archive:
                slide = ET.fromstring(archive.read('ppt/slides/slide1.xml'))
                ns = {'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
                      'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
                self.assertIsNone(slide.find('p:cSld/p:bg', ns), 'background=none must not export explicit background')
                self.assertFalse(any(n.startswith('ppt/media/') for n in archive.namelist()))
                names = {e.get('name') for e in slide.findall('.//p:cNvPr', ns)}
                self.assertIn('bar.bc', names)
                self.assertIn('edge.ca', names)
                self.assertTrue(slide.findall('.//a:t', ns))


if __name__ == '__main__': unittest.main()
