import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ppp/scripts'))
from edge_geometry import smooth_contours,curve_commands,compact,expand,staircase_candidates

class EdgeGeometryTests(unittest.TestCase):
 def test_circle_has_cubics_and_only_half_pixel_coordinates(self):
  y,x=np.mgrid[:60,:60];mask=(x-30)**2+(y-30)**2<20**2
  commands=curve_commands(smooth_contours(mask,3))
  self.assertTrue(any(c[0]=='C' for c in commands))
  self.assertTrue(all(v*2==int(v*2) for c in commands for v in c[1:]))
 def test_long_straight_edge_is_single_line(self):
  commands=curve_commands([[[0,0],[40,0],[40,20],[0,20]]])
  self.assertEqual(sum(c[0]=='L' for c in commands),4)
 def test_geometry_staircase_detector_is_not_always_pass(self):
  self.assertGreater(staircase_candidates([['M',0,0],['L',2,0],['L',2,2],['L',4,2],['L',4,4]]),0)
 def test_references_reuse_geometry_without_reducing_shape_count(self):
  one=[['M',0,0],['L',10,0],['L',10,10],['L',0,10],['Z']]
  two=[[c[0],*[v+20 for v in c[1:]]] for c in one]
  groups=[{'id':'particles','paths':[{'fill':'#AABBCC','commands':one},{'fill':'#AABBCC','commands':two}]}]
  packed=compact(groups,100,100)
  self.assertEqual(len(packed['definitions']),1)
  self.assertEqual(len(packed['groups'][0]['paints']),1)
  expanded=expand(packed)
  self.assertEqual(len(expanded['groups'][0]['paths']),2)
  self.assertEqual(expanded['groups'][0]['paths'][1]['commands'],two)
 def test_reference_expansion_enforces_budget(self):
  data={'version':3,'width':100,'height':100,'definitions':{'p1':[['M',0,0],['L',1,0],['L',1,1],['Z']]},'groups':[{'id':'x','paints':['#112233'],'default_paint':0,'items':[{'ref':'p1','at':[0,0]}]*1001}]}
  with self.assertRaisesRegex(ValueError,'1000'):expand(data)

if __name__=='__main__':unittest.main()
