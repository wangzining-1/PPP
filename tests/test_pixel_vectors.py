import importlib.util
from pathlib import Path
import tempfile
import unittest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'ppp/scripts/pixel_vectors.py'


class PixelVectorsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'Executable pixel vector converter is missing')
        spec = importlib.util.spec_from_file_location('pixel_vectors', SCRIPT)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def test_exact_visible_rgba_and_vertical_merging(self):
        im = Image.new('RGBA', (5, 3), (200, 10, 30, 128))
        im.putpixel((4, 2), (90, 80, 70, 0))
        rects = self.tool.rectangles(im, 100)
        self.assertEqual(len(rects), 2)
        out = Image.new('RGBA', im.size)
        coverage = set()
        for x, y, w, h, rgba in rects:
            for yy in range(y, y+h):
                for xx in range(x, x+w):
                    self.assertNotIn((xx, yy), coverage)
                    coverage.add((xx, yy))
                    out.putpixel((xx, yy), tuple(rgba))
        for a, b in zip(im.get_flattened_data(), out.get_flattened_data()):
            self.assertEqual(a if a[3] else (0, 0, 0, 0), b)

    def test_budget_fails_without_quantizing(self):
        im = Image.new('RGBA', (3, 1))
        im.putdata([(1, 2, 3, 255), (4, 5, 6, 255), (7, 8, 9, 255)])
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.tool.rectangles(im, 2)

    def test_formats_and_multiframe_selection(self):
        with tempfile.TemporaryDirectory() as td:
            for ext in ['png', 'bmp', 'tiff', 'webp', 'jpg']:
                p = Path(td) / ('sample.' + ext)
                Image.new('RGB', (4, 2), (25, 40, 80)).save(p)
                im, meta = self.tool.load_image(p, None)
                self.assertEqual(im.size, (4, 2))
                self.assertEqual(meta['frame'], 0)
            p = Path(td) / 'multi.gif'
            Image.new('RGB', (2, 2), 'red').save(p, save_all=True,
                append_images=[Image.new('RGB', (2, 2), 'blue')])
            with self.assertRaisesRegex(ValueError, 'frame'):
                self.tool.load_image(p, None)
            im, meta = self.tool.load_image(p, 1)
            self.assertEqual(im.getpixel((0, 0)), (0, 0, 255, 255))

    def test_svg_is_geometry_only(self):
        svg = self.tool.svg_text(3, 2, [(0, 0, 3, 2, (255, 0, 0, 128))])
        self.assertIn('<rect ', svg)
        self.assertNotIn('<image', svg)
        self.assertNotIn('base64', svg)
        self.assertIn('fill-opacity=', svg)


if __name__ == '__main__':
    unittest.main()
