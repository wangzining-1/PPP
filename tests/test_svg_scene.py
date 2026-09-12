import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('svg_to_scene', Path(__file__).resolve().parents[1] / 'ppp/scripts/svg_to_scene.py')
svg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(svg)


class SVGSceneTests(unittest.TestCase):
    def convert(self, body, attrs='width="100" height="80"'):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.svg'
            source.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>', encoding='utf-8')
            return svg.import_svg(source)

    def test_transformed_cubic_and_inherited_fill(self):
        data = self.convert('<g transform="translate(10,20)" fill="#123456"><path transform="scale(2)" d="M1 2 C3 4 5 6 7 8Z"/></g>')
        shape = data['elements'][0]
        self.assertEqual(shape['fill'], '#123456')
        self.assertEqual(shape['commands'][0], {'op': 'M', 'x': 12, 'y': 24})
        self.assertEqual(shape['commands'][1], {'op': 'C', 'x1': 16, 'y1': 28, 'x2': 20, 'y2': 32, 'x': 24, 'y': 36})
        self.assertEqual(shape['commands'][-1], {'op': 'Z'})

    def test_arcs_and_quadratics_are_native_cubics(self):
        data = self.convert('<path d="M0 0 Q10 20 20 0 A10 10 0 0 1 40 0"/>')
        commands = data['elements'][0]['commands']
        self.assertEqual([c['op'] for c in commands], ['M'] + ['C']*5)
        self.assertAlmostEqual(commands[1]['x1'], 20/3)
        self.assertEqual(commands[-1]['x'], 40)

    def test_primitives_and_viewbox(self):
        data = self.convert('<rect x="10" y="20" width="30" height="10"/><circle cx="50" cy="40" r="5"/><polyline points="0,0 1,1" fill="none"/>', 'width="200" height="160" viewBox="0 0 100 80"')
        self.assertEqual(len(data['elements']), 3)
        self.assertEqual(data['elements'][0]['commands'][0], {'op': 'M', 'x': 20, 'y': 40})

    def test_text_remains_text(self):
        data = self.convert('<text x="10" y="30" font-size="20" font-family="Arial">Editable</text>')
        text = data['elements'][0]
        self.assertEqual(text['type'], 'text')
        self.assertEqual(text['text'], 'Editable')
        self.assertEqual(text['y'], 14)

    def test_unsupported_features_fail(self):
        cases = ['<image href="x.png"/>', '<defs><linearGradient id="a"/></defs>',
                 '<path d="M0 0L1 1" fill="url(#a)"/>', '<rect width="2" height="2" clip-path="url(#a)"/>',
                 '<path fill-rule="evenodd" d="M0 0L20 0L20 20Z M5 5L10 5L10 10Z"/>',
                 '<text><tspan>A</tspan></text>', '<style>path{fill:red}</style>',
                 '<g opacity="0.5"><rect width="2" height="2"/></g>',
                 '<line x2="20" transform="scale(2,3)" stroke="red"/>']
        for body in cases:
            with self.subTest(body=body), self.assertRaises(svg.UnsupportedSVG):
                self.convert(body)

    def test_style_overrides_presentation_attribute(self):
        shape = self.convert('<rect width="10" height="10" fill="red" style="fill:blue;fill-opacity:0.5"/>')['elements'][0]
        self.assertEqual(shape['fill'], '#0000FF')
        self.assertEqual(shape['fillOpacity'], .5)

    def test_nonzero_compound_path_retains_holes_and_relative_moveto(self):
        shape = self.convert('<path d="M0 0L20 0L20 20L0 20Z m5 5v10h10v-10Z"/>')['elements'][0]
        self.assertEqual(sum(c['op'] == 'Z' for c in shape['commands']), 2)
        moves = [c for c in shape['commands'] if c['op'] == 'M']
        self.assertEqual(moves[1], {'op': 'M', 'x': 5, 'y': 5})


if __name__ == '__main__':
    unittest.main()
