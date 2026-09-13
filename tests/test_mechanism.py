import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'ppp/scripts/mechanism.py'


def graph():
    return {'version': 1, 'reviewed': True,
            'nodes': [{'id': n, 'label': n} for n in 'ABCD'],
            'edges': [dict(id='ab', source='A', target='B', kind='activation', evidence='User context', status='supported'),
                      dict(id='bc', source='B', target='C', kind='inhibition', evidence='User context', status='supported'),
                      dict(id='bd', source='B', target='D', kind='unknown', evidence='Blurred arrow ROI', status='uncertain')]}


class MechanismTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'Missing causal graph compiler')
        spec = importlib.util.spec_from_file_location('mechanism', SCRIPT)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def test_order_and_uncertainty(self):
        result = self.tool.compile_graph(graph())
        layers = result['plan']['layers']
        self.assertLess(layers['A'], layers['B'])
        self.assertLess(layers['B'], layers['C'])
        self.assertEqual(layers['D'], 0)
        edge = [e for e in result['scene']['elements'] if e['id'] == 'edge.bd'][0]
        self.assertNotIn('arrowEnd', edge)
        self.assertEqual(result['plan']['uncertain_edges'], ['bd'])

    def test_feedback_is_retained(self):
        data = graph()
        data['edges'].append(dict(id='ca', source='C', target='A', kind='activation', evidence='Context', status='supported'))
        result = self.tool.compile_graph(data)
        self.assertIn(['A', 'B', 'C'], result['plan']['cycles'])
        self.assertTrue(any(e['id'] == 'edge.ca' for e in result['scene']['elements']))
        self.assertEqual(len(result['plan']['edge_order']), 4)

    def test_inhibition_has_bar_not_activation_arrow(self):
        elements = self.tool.compile_graph(graph())['scene']['elements']
        main = next(e for e in elements if e['id'] == 'edge.bc')
        self.assertNotIn('arrowEnd', main)
        self.assertTrue(any(e['id'] == 'bar.bc' for e in elements))

    def test_rejects_invalid_and_unreviewed_input(self):
        for mutate in [lambda d: d.update(reviewed=False),
                       lambda d: d['edges'][0].update(target='missing'),
                       lambda d: d['edges'][0].update(kind='invented'),
                       lambda d: d['edges'][0].update(evidence=''),
                       lambda d: d['nodes'].append(d['nodes'][0].copy())]:
            data = graph(); mutate(data)
            with self.assertRaises(ValueError): self.tool.compile_graph(data)

    def test_deterministic_cache_and_changed_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self.tool.build(graph(), root)
            second = self.tool.build(graph(), root)
            self.assertFalse(first['cache_hit']); self.assertTrue(second['cache_hit'])
            data = graph(); data['nodes'][0]['label'] = 'New label'
            third = self.tool.build(data, root)
            self.assertNotEqual(first['key'], third['key'])
            self.assertTrue(Path(first['scene']).exists())
            scene = Path(second['scene']); scene.write_text('{}')
            repaired = self.tool.build(graph(), root)
            self.assertFalse(repaired['cache_hit'])
            self.assertIn('elements', json.loads(Path(repaired['scene']).read_text()))

    def test_feedback_routes_outside_entity_boxes(self):
        data = graph()
        data['edges'].append(dict(id='ca', source='C', target='A', kind='activation', evidence='Context', status='supported'))
        elements = self.tool.compile_graph(data)['scene']['elements']
        node = next(e for e in elements if e['id'] == 'node.C')
        route = next(e for e in elements if e['id'] == 'route.ca')
        self.assertGreaterEqual(route['commands'][0]['x'], node['x'] + node['width'])

    def test_malformed_cache_manifest_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as td:
            first = self.tool.build(graph(), td)
            manifest = Path(first['scene']).parent / 'manifest.json'
            manifest.write_text(json.dumps({'key': first['key'], 'files': []}))
            self.assertFalse(self.tool.build(graph(), td)['cache_hit'])

    def test_chinese_labels_wrap_inside_box(self):
        data = graph(); data['nodes'][0]['label'] = '外泌体介导的邻近标记机制与细胞信号转导'
        result = self.tool.compile_graph(data)
        label = next(e for e in result['scene']['elements'] if e['id'] == 'label.A')
        self.assertLessEqual(max(map(len, label['text'].splitlines())), 9)

    def test_grid_budget_and_prompt(self):
        result = self.tool.compile_graph(graph())
        for element in result['scene']['elements']:
            for key in ('x','y','x1','y1','x2','y2','width','height'):
                if key in element: self.assertEqual(element[key] * 2, round(element[key] * 2))
        self.assertIn('uncertain', result['image_prompt'])
        with self.assertRaises(ValueError): self.tool.compile_graph(graph(), max_shapes=1)


if __name__ == '__main__': unittest.main()
