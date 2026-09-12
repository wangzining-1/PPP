"""Bounded integration: native XML, cubic, hole contours, text, alpha, arrows."""
import json, os, subprocess, zipfile, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.build'/'scene-tests'; OUT.mkdir(parents=True,exist_ok=True)
scene={'version':1,'width':640,'height':360,'background':'#FFFFFF','elements':[
 {'id':'cell','type':'ellipse','x':30,'y':40,'width':170,'height':130,'fill':'#77CCAA','opacity':0.5,'stroke':'#225544','strokeWidth':2},
 {'id':'label','type':'text','x':65,'y':88,'width':120,'height':35,'text':'Cell α','fontSize':24,'fill':'#112233'},
 {'id':'signal','type':'line','x1':205,'y1':110,'x2':325,'y2':110,'stroke':'#333333','strokeWidth':3,'arrowEnd':'triangle'},
 {'id':'curve','type':'path','fill':'none','stroke':'#CC3344','strokeWidth':3,'commands':[{'op':'M','x':40,'y':240},{'op':'C','x1':100,'y1':175,'x2':190,'y2':330,'x':270,'y':230}]},
 {'id':'hole','type':'path','fill':'#8877CC','commands':[{'op':'M','x':350,'y':40},{'op':'L','x':540,'y':40},{'op':'L','x':540,'y':190},{'op':'L','x':350,'y':190},{'op':'Z'}, {'op':'M','x':390,'y':80},{'op':'L','x':390,'y':150},{'op':'L','x':500,'y':150},{'op':'L','x':500,'y':80},{'op':'Z'}]},
]}
(OUT/'fixture.json').write_text(json.dumps(scene),encoding='utf8')
for name in ['fixture.pptx','fixture.svg','fixture.png']:
 (OUT/name).unlink(missing_ok=True)
runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
env=dict(os.environ,RUNTIME_NODE_MODULES=str(runtime/'node_modules'))
cmd=[str(runtime/'bin/node.exe'),str(ROOT/'ppp/scripts/scene_to_pptx.mjs'),str(OUT/'fixture.json'),str(OUT/'fixture.pptx'),'--render',str(OUT/'fixture.png')]
subprocess.run(cmd,check=True,env=env)
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
with zipfile.ZipFile(OUT/'fixture.pptx') as z:
 xml=ET.fromstring(z.read('ppt/slides/slide1.xml'))
 assert len(xml.findall('.//p:sp',ns))==5
 assert not xml.findall('.//p:pic',ns)
 assert xml.find('.//a:cubicBezTo',ns) is not None
 assert len(xml.findall('.//a:close',ns))==2
 assert xml.find('.//a:tailEnd',ns).get('type')=='triangle'
 assert 'Cell α' in ''.join(xml.itertext())
 assert any(a.get('val')=='50000' for a in xml.findall('.//a:alpha',ns))
 assert [x.get('name') for x in xml.findall('.//p:sp/p:nvSpPr/p:cNvPr',ns)]==[e['id'] for e in scene['elements']]
 assert not any(n.startswith('ppt/media/') for n in z.namelist())
assert (OUT/'fixture.png').stat().st_size>100
import resvg_py
from PIL import Image
(OUT/'reference.png').write_bytes(resvg_py.svg_to_bytes(svg_path=str(OUT/'fixture.svg')))
rendered=Image.open(OUT/'fixture.png').convert('RGB')
reference=Image.open(OUT/'reference.png').convert('RGB')
assert rendered.size==reference.size==(640,360)
assert rendered.getpixel((430,110))==(255,255,255), 'Hole must expose background'
assert rendered.getpixel((370,110))==(136,119,204), 'Ring fill changed'
assert rendered.getpixel((120,60))==reference.getpixel((120,60)), 'Alpha fill changed'
# Negative contract: fail, never silently rasterize unsupported image elements.
bad=dict(scene,elements=[{'id':'raster','type':'image'}])
(OUT/'invalid.json').write_text(json.dumps(bad),encoding='utf8')
failure=subprocess.run([cmd[0],cmd[1],str(OUT/'invalid.json'),str(OUT/'invalid.pptx')],env=env,capture_output=True,text=True)
assert failure.returncode and 'Unsupported type image' in failure.stderr
for field,value in [('rotation',45),('strokeDasharray',[3,2])]:
 bad=dict(scene,elements=[dict(scene['elements'][0],**{field:value})])
 (OUT/'invalid.json').write_text(json.dumps(bad),encoding='utf8')
 failure=subprocess.run([cmd[0],cmd[1],str(OUT/'invalid.json'),str(OUT/'invalid.pptx')],env=env,capture_output=True,text=True)
 assert failure.returncode and f'field {field}' in failure.stderr
bad=dict(scene,transform='rotate(45)')
(OUT/'invalid.json').write_text(json.dumps(bad),encoding='utf8')
failure=subprocess.run([cmd[0],cmd[1],str(OUT/'invalid.json'),str(OUT/'invalid.pptx')],env=env,capture_output=True,text=True)
assert failure.returncode and 'scene field transform' in failure.stderr
print('PASS native scene integration; PNG from saved PPTX via Artifact Tool; PowerPoint untested')
