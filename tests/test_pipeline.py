import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'ppp/scripts/ppp.py'


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'Local multi-stage pipeline is missing')
        spec = importlib.util.spec_from_file_location('ppp', SCRIPT)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def test_comparison_detects_missing_thin_element_and_exact_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            im = Image.new('RGB', (64, 64), 'white')
            im.save(root / 'a.png')
            report = self.tool.compare(root / 'a.png', root / 'a.png', root / 'exact')
            self.assertEqual(report['rgb_max_error'], 0)
            for y in range(64):
                im.putpixel((30, y), (0, 0, 0))
            im.save(root / 'b.png')
            report = self.tool.compare(root / 'a.png', root / 'b.png', root / 'diff')
            self.assertGreater(report['rgb_max_error'], 0)
            self.assertGreater(report['changed_pixel_fraction'], 0)
            self.assertTrue(report['worst_tiles'])

    def test_no_unreviewed_text_erasure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            Image.new('RGB', (32, 32), 'white').save(root / 'source.png')
            labels = {'reviewed': False, 'labels': [{'text': 'X', 'box': [2, 2, 10, 10]}]}
            (root / 'labels.json').write_text(json.dumps(labels))
            with self.assertRaisesRegex(ValueError, 'reviewed'):
                self.tool.erase(root / 'source.png', root / 'labels.json', root / 'erase')
            self.assertFalse((root / 'erase').exists())

    def test_trace_rejects_silent_alpha_loss(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            Image.new('RGBA', (20, 20), (255, 0, 0, 128)).save(root / 'alpha.png')
            with self.assertRaisesRegex(ValueError, 'alpha'):
                self.tool.trace(root / 'alpha.png', root / 'trace')
            self.assertFalse((root / 'trace').exists())

    def test_audit_matches_text_to_its_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scene = {'elements': [{'id': 'a', 'type': 'text', 'text': 'cat'},
                                  {'id': 'b', 'type': 'text', 'text': 'dog'}]}
            (root / 'scene.json').write_text(json.dumps(scene))
            xml = '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
            <p:sp><p:nvSpPr><p:cNvPr name="a"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>dog</a:t></a:r></a:p></p:txBody></p:sp>
            <p:sp><p:nvSpPr><p:cNvPr name="b"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>concatenate</a:t></a:r></a:p></p:txBody></p:sp>
            </p:spTree></p:cSld></p:sld>'''
            with zipfile.ZipFile(root / 'bad.pptx', 'w') as archive:
                archive.writestr('ppt/slides/slide1.xml', xml)
            result = self.tool.audit(root / 'bad.pptx', root / 'scene.json')
            self.assertFalse(result['scene_contract_pass'])

    def test_text_merge_produces_actual_text_elements(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scene = {'version': 1, 'width': 200, 'height': 100, 'elements': []}
            labels = {'reviewed': True, 'labels': [{'id': 'label1', 'text': 'ATP',
                      'box': [10, 20, 40, 18], 'font_size': 16, 'font_family': 'Arial', 'color': '#112233'}]}
            (root / 'scene.json').write_text(json.dumps(scene))
            (root / 'labels.json').write_text(json.dumps(labels))
            result = self.tool.merge_labels(root / 'scene.json', root / 'labels.json', root / 'merged.json')
            self.assertEqual(result['elements'][-1]['type'], 'text')
            self.assertEqual(result['elements'][-1]['text'], 'ATP')


if __name__ == '__main__':
    unittest.main()
