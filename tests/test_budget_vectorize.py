"""CLI acceptance tests for semantic, background-free vector budgets."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw


SCRIPT = Path(__file__).resolve().parents[1] / 'ppp/scripts/budget_vectorize.py'
SVG = '{http://www.w3.org/2000/svg}'


class BudgetVectorizeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'Semantic budget vectorizer is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.width, self.height = 80, 64
        self.source = Image.new('RGB', (self.width, self.height))
        for y in range(self.height):
            for x in range(self.width):
                self.source.putpixel((x, y), (255 - y // 8, 253 - y // 8, 255))
        self.config = {'width': self.width, 'height': self.height,
                       'background_tolerance': 18, 'units': []}

    def add_unit(self, name, box, color):
        mask = Image.new('L', self.source.size)
        ImageDraw.Draw(mask).ellipse(box, fill=255)
        mask.save(self.root / f'{name}.png')
        ImageDraw.Draw(self.source).ellipse(box, fill=color)
        self.config['units'].append({'id': name, 'mask': f'{name}.png',
                                     'colors': 6, 'protected': False})
        return mask

    def run_build(self, budget=1000):
        self.source.save(self.root / 'graphics.png')
        (self.root / 'semantic.json').write_text(json.dumps(self.config), encoding='utf-8')
        proposal=subprocess.run([sys.executable,str(SCRIPT),'plan',str(self.root/'graphics.png'),str(self.root/'semantic.json'),'--max-shapes',str(budget)],capture_output=True,text=True)
        if proposal.returncode:return proposal
        # Synthetic tests explicitly authorize their fixture builds; real use requires user confirmation.
        plan_id=json.loads(proposal.stdout)['plan']
        return subprocess.run([sys.executable, str(SCRIPT), 'build',
                               str(self.root / 'graphics.png'),
                               str(self.root / 'semantic.json'), str(self.root / 'out'),
                               '--max-shapes', str(budget),'--confirm-plan',plan_id], capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=90)

    def successful_output(self, result):
        self.assertEqual(result.returncode, 0, result.stderr[-3000:] + result.stdout[-1000:])
        root = self.root / 'out'
        for filename in ['graphics.svg', 'budget.json', 'groups.json', 'background-mask.png']:
            self.assertTrue((root / filename).is_file(), filename)
        report = json.loads((root / 'budget.json').read_text(encoding='utf-8'))
        for key in ['vector_shapes', 'subpaths', 'groups', 'background_vector_shapes', 'stage_counts']:
            self.assertIn(key, report)
        self.assertEqual(report['background_vector_shapes'], 0)
        svg = ET.parse(root / 'graphics.svg').getroot()
        self.assertFalse(list(svg.iter(SVG + 'image')), 'Raster embedding is not vectorization')
        self.assertFalse(list(svg.iter(SVG + 'rect')), 'Output should not recreate a canvas rectangle')
        return report, svg

    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0, 'Invalid input must fail instead of claiming acceptance')
        report = self.root / 'out/budget.json'
        if report.exists():
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertTrue(data.get('ok') is False or data.get('passed') is False,
                            'Failure may not leave an apparently successful budget report')

    def test_gradient_background_has_no_vector_objects(self):
        report, svg = self.successful_output(self.run_build())
        self.assertEqual(report['vector_shapes'], 0)
        self.assertEqual(report['subpaths'], 0)
        self.assertFalse(list(svg.iter(SVG + 'path')))
        mask = Image.open(self.root / 'out/background-mask.png').convert('L')
        self.assertGreater(mask.getpixel((40, 32)), 0)

    def test_semantic_units_survive_small_budget_and_merge_speckles(self):
        self.add_unit('red-cell', (8, 12, 32, 46), (202, 71, 78))
        self.add_unit('blue-cell', (46, 12, 72, 46), (55, 155, 202))
        # Similar-color single-pixel noise must not consume independent shape budget.
        for x in range(14, 29, 2):
            for y in range(20, 39, 2):
                self.source.putpixel((x, y), (209, 78, 84))
        report, svg = self.successful_output(self.run_build(4))
        self.assertLessEqual(report['vector_shapes'], 4)
        self.assertGreaterEqual(report['vector_shapes'], 2)
        self.assertGreaterEqual(len(list(svg.iter(SVG + 'g'))), 2)
        # Render the exported artifact, not merely its report, to catch discarded subjects.
        import io
        import resvg_py
        png = resvg_py.svg_to_bytes(svg_string=ET.tostring(svg, encoding='unicode'))
        rendered = Image.open(io.BytesIO(png)).convert('RGBA')
        for point, target in [((20, 29), (202, 71, 78)), ((59, 29), (55, 155, 202))]:
            actual = rendered.getpixel(point)
            self.assertGreater(actual[3], 240)
            self.assertLess(max(abs(a - b) for a, b in zip(actual[:3], target)), 25)
        self.assertEqual(rendered.getpixel((0, 0))[3], 0)

    def test_budget_smaller_than_semantic_unit_count_fails(self):
        self.add_unit('a', (8, 12, 32, 46), (202, 71, 78))
        self.add_unit('b', (46, 12, 72, 46), (55, 155, 202))
        self.assert_rejected(self.run_build(1))

    def test_overlapping_review_masks_fail(self):
        self.add_unit('a', (8, 12, 42, 46), (202, 71, 78))
        self.add_unit('b', (30, 12, 72, 46), (55, 155, 202))
        self.assert_rejected(self.run_build())

    def test_wrong_mask_dimensions_fail(self):
        self.add_unit('a', (8, 12, 32, 46), (202, 71, 78))
        Image.new('L', (20, 20), 255).save(self.root / 'a.png')
        self.assert_rejected(self.run_build())

    def test_full_build_requires_explicit_plan_confirmation(self):
        self.source.save(self.root/'graphics.png')
        (self.root/'semantic.json').write_text(json.dumps(self.config))
        result=subprocess.run([sys.executable,str(SCRIPT),'build',str(self.root/'graphics.png'),str(self.root/'semantic.json'),str(self.root/'out')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('--confirm-plan',result.stderr)
        self.assertFalse((self.root/'out').exists())

    def test_changed_input_invalidates_confirmation(self):
        self.source.save(self.root/'graphics.png')
        (self.root/'semantic.json').write_text(json.dumps(self.config))
        p=subprocess.run([sys.executable,str(SCRIPT),'plan',str(self.root/'graphics.png'),str(self.root/'semantic.json')],capture_output=True,text=True)
        plan_id=json.loads(p.stdout)['plan']
        self.source.putpixel((10,10),(1,2,3));self.source.save(self.root/'graphics.png')
        result=subprocess.run([sys.executable,str(SCRIPT),'build',str(self.root/'graphics.png'),str(self.root/'semantic.json'),str(self.root/'out'),'--confirm-plan',plan_id],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('inputs changed',result.stderr)
        self.assertFalse((self.root/'out').exists())

    def test_partial_alpha_is_rejected_without_flattening(self):
        self.source=self.source.convert('RGBA')
        self.source.putpixel((30,30),(220,50,60,128))
        self.assert_rejected(self.run_build())

    def test_one_pixel_functional_line_survives(self):
        mask=Image.new('L',self.source.size)
        ImageDraw.Draw(mask).line((20,20,20,40),fill=255,width=1)
        ImageDraw.Draw(self.source).line((20,20,20,40),fill=(150,30,30),width=1)
        mask.save(self.root/'line.png')
        self.config['units']=[{'id':'line','mask':'line.png','colors':1,'protected':True}]
        report,svg=self.successful_output(self.run_build())
        self.assertEqual(report['vector_shapes'],1)
        import io,resvg_py
        rendered=Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=ET.tostring(svg,encoding='unicode')))).convert('RGBA')
        self.assertGreater(rendered.getpixel((20,30))[3],240)

    def test_unassigned_foreground_is_reported(self):
        ImageDraw.Draw(self.source).rectangle((20,20,40,40),fill=(200,30,30))
        report,_=self.successful_output(self.run_build())
        self.assertGreater(report['unassigned_pixels'],400)
        self.assertNotEqual(report['visual_acceptance'],'pass')

    def test_diagonal_line_has_no_rectangle_artifact_and_colors_no_gap(self):
        mask=Image.new('L',self.source.size)
        ImageDraw.Draw(mask).line((10,10,30,30),fill=255,width=1)
        ImageDraw.Draw(mask).rectangle((40,10,60,30),fill=255)
        d=ImageDraw.Draw(self.source)
        d.line((10,10,30,30),fill=(200,20,20),width=1)
        d.rectangle((40,10,50,30),fill=(20,40,180));d.rectangle((51,10,60,30),fill=(180,150,20))
        mask.save(self.root/'unit.png')
        self.config['units']=[{'id':'test','mask':'unit.png','colors':3,'protected':True}]
        _,svg=self.successful_output(self.run_build())
        import io,resvg_py
        im=Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=ET.tostring(svg,encoding='unicode')))).convert('RGBA')
        self.assertEqual(im.getpixel((12,28))[3],0,'Diagonal must not become a bounding rectangle')
        # A subpixel diagonal has antialiased coverage; the shared solid-fill edge must remain opaque.
        self.assertGreater(im.getpixel((20,20))[3],128)
        for pt in [(50,20),(51,20)]:self.assertGreater(im.getpixel(pt)[3],250,f'No shared-edge gaps at {pt}')

    def test_pptx_entry_rejects_forged_over_budget_groups(self):
        folder=self.root/'build';folder.mkdir()
        path={'fill':'#AA3344','contours':[[[1,1],[10,1],[10,10],[1,10]]]}
        (folder/'groups.json').write_text(json.dumps({'width':80,'height':64,'groups':[{'id':'spoof','paths':[path]*1001}]}))
        result=subprocess.run([sys.executable,str(SCRIPT),'pptx',str(self.root/'not-needed.pptx'),str(folder),str(self.root/'bad.pptx')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('1000',result.stderr)
        self.assertFalse((self.root/'bad.pptx').exists())

    def test_native_groups_and_text_survive_ppt_export(self):
        self.add_unit('cell',(8,12,32,46),(202,71,78))
        self.successful_output(self.run_build())
        p='http://schemas.openxmlformats.org/presentationml/2006/main'
        a='http://schemas.openxmlformats.org/drawingml/2006/main'
        template=self.root/'template.pptx'
        slide=f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="label"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>NFAT</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
        with zipfile.ZipFile(template,'w') as z:
            z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{p}"><p:sldSz cx="762000" cy="609600"/></p:presentation>')
            z.writestr('ppt/slides/slide1.xml',slide)
        result=subprocess.run([sys.executable,str(SCRIPT),'pptx',str(template),str(self.root/'out'),str(self.root/'native.pptx')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout);self.assertEqual(report['groups'],1);self.assertEqual(report['text_boxes'],1)
        with zipfile.ZipFile(self.root/'native.pptx') as z:
            raw=z.read('ppt/slides/slide1.xml')
            self.assertIn(b"encoding='utf-8'",raw)
            xml=ET.fromstring(raw)
            for pt in xml.findall(f'.//{{{a}}}pt'):
                for key in ('x','y'):self.assertRegex(pt.get(key),r'^-?\d+$')
        self.assertEqual(xml.find(f'.//{{{a}}}t').text,'NFAT')
        self.assertTrue(xml.findall(f'.//{{{p}}}grpSp/{{{p}}}sp'))


if __name__ == '__main__':
    unittest.main()
