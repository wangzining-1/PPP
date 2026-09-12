"""Self-authored integration fixture; contains no user figure or private data."""
import json,sys
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
im=Image.new('RGB',(100,100),'white');d=ImageDraw.Draw(im)
d.ellipse((10,10,45,45),fill='#4499BB');d.ellipse((14,13,35,35),fill='#BBEEDD')
d.polygon([(54,45),(83,12),(91,20),(62,53)],fill='#997755')
im.save(root/'source.png');units=[]
for name,box in [('cell',(10,10,45,45)),('arrow',(54,12,91,53))]:
 mask=Image.new('L',(100,100));md=ImageDraw.Draw(mask)
 if name=='cell':md.ellipse(box,fill=255)
 else:md.polygon([(54,45),(83,12),(91,20),(62,53)],fill=255)
 mask.save(root/f'{name}.png');units.append({'id':name,'mask':f'{name}.png','colors':4})
(root/'semantic.json').write_text(json.dumps({'width':100,'height':100,'supersample':3,'units':units}))
(root/'text.json').write_text(json.dumps({'version':1,'width':100,'height':100,'background':'none','elements':[{'id':'label','type':'text','x':20,'y':65,'width':65,'height':20,'text':'PPP test','fontSize':12,'fill':'#111111'}]}))
