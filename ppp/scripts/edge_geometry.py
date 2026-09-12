"""Supersampled contour analysis, 0.5px geometry, and explicit edge QA."""
import math
import cv2
import numpy as np

def snap(v):return round(float(v)*2)/2

def smooth_contours(mask,scale=3):
 if scale not in (2,3,4):raise ValueError('supersample must be 2, 3, or 4')
 # Interpolate the boundary field before contour extraction. This is not new image detail.
 field=cv2.resize(mask.astype(np.float32),(mask.shape[1]*scale,mask.shape[0]*scale),interpolation=cv2.INTER_CUBIC)
 field=cv2.GaussianBlur(field,(0,0),.45*scale)
 binary=(field>.45).astype('uint8')
 cs,_=cv2.findContours(binary,cv2.RETR_TREE,cv2.CHAIN_APPROX_NONE)
 result=[]
 for c in cs:
  poly=cv2.approxPolyDP(c,.5*scale,True).reshape(-1,2)
  if len(poly)<3:
   # Thin functional elements get a supersampled min-area outline, not an axis-aligned box.
   poly=cv2.boxPoints(cv2.minAreaRect(c)).reshape(-1,2)
  points=[[snap((x+.5)/scale),snap((y+.5)/scale)] for x,y in poly]
  unique=[]
  for p in points:
   if not unique or p!=unique[-1]:unique.append(p)
  if len(unique)>2:result.append(unique)
 return result

def curve_commands(contours):
 commands=[]
 for polygon in contours:
  p=np.asarray(polygon,float);n=len(p)
  if n<3:continue
  commands.append(['M',*p[0].tolist()])
  for i in range(n):
   before,a,b,after=p[(i-1)%n],p[i],p[(i+1)%n],p[(i+2)%n]
   v=b-a;length=np.linalg.norm(v)
   def turn(u,v):
    norms=np.linalg.norm(u)*np.linalg.norm(v)
    return 180 if norms==0 else math.degrees(math.acos(np.clip(np.dot(u,v)/norms,-1,1)))
   # Long straight sides remain a single line; sharp corners are not rounded away.
   bend=max(turn(a-before,v),turn(v,after-b))
   if (length>8 and bend<8) or bend>55:
    commands.append(['L',*b.tolist()])
   else:
    c1=a+(b-before)/6;c2=b-(after-a)/6
    # Keep handles within the semantic contour bounds while retaining curved tangents.
    c1=np.clip(c1,p.min(0),p.max(0));c2=np.clip(c2,p.min(0),p.max(0))
    commands.append(['C',*[snap(x) for x in [*c1,*c2,*b]]])
  commands.append(['Z'])
 return commands

def staircase_candidates(commands):
 """Geometry-only flag for two successive same-direction horizontal/vertical steps.

 This cannot certify every edge of a 400% rendered image; visual QA remains pending.
 """
 positions=[];previous=None;run=[];count=0
 for cmd in commands:
  if cmd[0]=='L' and previous is not None:
   dx,dy=cmd[1]-previous[0],cmd[2]-previous[1]
   axis=0 if dy==0 and dx!=0 else (1 if dx==0 and dy!=0 else -1)
   if axis>=0:
    run.append((axis,1 if (dx if axis==0 else dy)>0 else -1))
    if len(run)>=4 and run[-4][0]!=run[-3][0] and run[-4]==run[-2] and run[-3]==run[-1]:count+=1
   else:run=[]
  else:run=[]
  if cmd[0] in ('M','L'):previous=cmd[1:3]
  elif cmd[0]=='C':previous=cmd[-2:]
  else:previous=None
 return count

def compact(groups,width,height):
 definitions={};seen={};packed=[]
 for group in groups:
  paints=[];items=[]
  for path in group['paths']:
   color=path['fill']
   if color not in paints:paints.append(color)
   cmds=path['commands'];pts=[(c[i],c[i+1]) for c in cmds for i in range(1,len(c),2)]
   ox=min(x for x,y in pts);oy=min(y for x,y in pts)
   relative=[[c[0],*[snap(v-(ox if i%2==1 else oy)) for i,v in enumerate(c[1:],1)]] for c in cmds]
   key=str(relative)
   if key not in seen:
    identifier=f'p{len(seen)+1}';seen[key]=identifier;definitions[identifier]=relative
   item={'ref':seen[key],'at':[ox,oy]}
   if paints.index(color):item['paint']=paints.index(color)
   items.append(item)
  packed.append({'id':group['id'],'paints':paints,'default_paint':0,'items':items})
 return {'version':3,'width':width,'height':height,'definitions':definitions,'groups':packed}

def expand(data):
 if data.get('version')!=3:return data
 groups=[];count=0
 for group in data['groups']:
  paths=[]
  for item in group['items']:
   count+=1
   if count>1000:raise ValueError('Expanded reference budget exceeds 1000')
   ox,oy=item['at'];commands=[];contours=[];points=[]
   for c in data['definitions'][item['ref']]:
    cmd=[c[0],*[snap(v+(ox if i%2==1 else oy)) for i,v in enumerate(c[1:],1)]]
    commands.append(cmd)
    if cmd[0]=='M':
     if points:contours.append(points)
     points=[]
    points.extend([[cmd[i],cmd[i+1]] for i in range(1,len(cmd),2)])
   if points:contours.append(points)
   paths.append({'fill':group['paints'][item.get('paint',group['default_paint'])],'commands':commands,'contours':contours})
  groups.append({'id':group['id'],'paths':paths})
 return {'width':data['width'],'height':data['height'],'groups':groups}
