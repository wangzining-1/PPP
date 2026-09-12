"""Budgeted, semantic-mask vectorization and native grouped PowerPoint export.

Masks are reviewed semantic inputs, not automatic object-recognition claims.
All image computation stays local. No raster objects are written into PPTX.
"""
from pathlib import Path
import argparse, copy, hashlib, json, math, sys, zipfile
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from PIL import Image
from edge_geometry import smooth_contours,curve_commands,staircase_candidates,compact,expand

A='http://schemas.openxmlformats.org/drawingml/2006/main'
P='http://schemas.openxmlformats.org/presentationml/2006/main'
S='http://www.w3.org/2000/svg'
NS={'a':A,'p':P}

def load_json(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save_json(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')

def background(rgb, cfg, base, protect, alpha):
 h,w=rgb.shape[:2]
 if cfg.get('background_model'):
  model=np.array(Image.open(base/cfg['background_model']).convert('RGB'))
  if model.shape!=rgb.shape:raise ValueError('Background model size mismatch')
 else:
  y,x=np.mgrid[0:h,0:w];x=x/max(w-1,1);y=y/max(h-1,1)
  model=sum(rgb[cy,cx].astype(float)*weight[...,None] for (cy,cx),weight in
    zip([(0,0),(0,w-1),(h-1,0),(h-1,w-1)],[(1-x)*(1-y),x*(1-y),(1-x)*y,x*y]))
 allowed=(np.max(abs(rgb.astype(float)-model),axis=2)<=cfg.get('background_tolerance',18)) & ~protect
 allowed |= alpha==0
 count,cc=cv2.connectedComponents(allowed.astype('uint8'),connectivity=4)
 seeds=cfg.get('background_seeds',[[0,0],[w-1,0],[0,h-1],[w-1,h-1]])
 codes=set()
 for x,y in seeds:
  if not(0<=x<w and 0<=y<h):raise ValueError('Background seed out of bounds')
  if allowed[y,x]:codes.add(cc[y,x])
 return np.isin(cc,list(codes)) | (alpha==0)

def palette(rgb,mask,k):
 pixels=rgb[mask];k=min(k,len(np.unique(pixels,axis=0)))
 lab=cv2.cvtColor(pixels.reshape(-1,1,3).astype(np.float32)/255,cv2.COLOR_RGB2LAB).reshape(-1,3)
 cv2.setRNGSeed(1234)
 _,labels,centers=cv2.kmeans(lab,k,None,(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,35,.08),1,cv2.KMEANS_PP_CENTERS)
 labels=labels.ravel();colors=np.array([np.median(pixels[labels==i],axis=0) for i in range(k)])
 grid=np.full(mask.shape,-1,np.int32);grid[mask]=labels
 return grid,colors

def adjacent_merge(grid,colors):
 # Merge only touching color regions. Larger palette class absorbs smaller.
 while True:
  pairs=set()
  for a,b in [(grid[:-1],grid[1:]),(grid[:,:-1],grid[:,1:])]:
   valid=(a>=0)&(b>=0)&(a!=b)
   pairs.update(tuple(sorted(p)) for p in zip(a[valid].tolist(),b[valid].tolist()))
  options=[(np.linalg.norm(colors[a]-colors[b]),a,b) for a,b in pairs if np.max(abs(colors[a]-colors[b]))<20]
  if not options:break
  _,a,b=min(options);na=np.count_nonzero(grid==a);nb=np.count_nonzero(grid==b)
  if na<nb:a,b=b,a;na,nb=nb,na
  grid[grid==b]=a  # Preserve the dominant body's original palette color.
 return grid,colors

def absorb_small(grid,limit=16):
 # Keep the dominant body. Small color islands adopt a touching majority.
 for color in list(np.unique(grid[grid>=0])):
  n,cc,stats,_=cv2.connectedComponentsWithStats((grid==color).astype('uint8'),8)
  for i in range(1,n):
   x,y,w,h,area=stats[i]
   if area>=limit or w>=4 or h>=4:continue
   component=cc==i
   ring=cv2.dilate(component.astype('uint8'),np.ones((3,3),np.uint8)).astype(bool)&~component
   vals=grid[ring];vals=vals[(vals>=0)&(vals!=color)]
   if len(vals):grid[component]=int(np.bincount(vals).argmax())
 return grid

def contours(grid,colors,scale=3):
 result=[]
 for c in np.unique(grid[grid>=0]):
  paths=smooth_contours(grid==c,scale)
  if paths:result.append({'fill':'#'+''.join(f'{int(round(v)):02X}' for v in colors[c]),'contours':paths,'commands':curve_commands(paths)})
 return result

def plan(image,semantic,max_shapes=1000):
 cfg=load_json(semantic);base=Path(semantic).resolve().parent
 digest=hashlib.sha256(Path(image).read_bytes()+Path(semantic).read_bytes())
 for unit in cfg['units']:digest.update((base/unit['mask']).read_bytes())
 if cfg.get('background_model'):digest.update((base/cfg['background_model']).read_bytes())
 digest.update(str(max_shapes).encode())
 return {'plan':digest.hexdigest()[:16],'units':len(cfg['units']),'max_shapes':max_shapes,'ss':cfg.get('supersample',3),'grid':0.5,'status':'awaiting_confirmation'}

def build(image,semantic,out,max_shapes=1000,confirmation=None):
 proposal=plan(image,semantic,max_shapes)
 if confirmation!=proposal['plan']:raise ValueError('Plan confirmation required or inputs changed; run plan and obtain user confirmation first')
 if not 1<=max_shapes<=1000:raise ValueError('max-shapes must be 1..1000')
 cfg=load_json(semantic);base=Path(semantic).resolve().parent;out=Path(out)
 unknown=set(cfg)-{'width','height','background_model','background_tolerance','background_seeds','units','supersample'}
 if unknown:raise ValueError(f'Unknown semantic configuration keys: {sorted(unknown)}')
 if out.exists():raise ValueError('Output directory already exists')
 rgba=np.array(Image.open(image).convert('RGBA'));rgb=rgba[:,:,:3];h,w=rgb.shape[:2]
 if np.any((rgba[:,:,3]>0)&(rgba[:,:,3]<255)):raise ValueError('Partial alpha is unsupported; preserve it through a native-opacity workflow')
 if (cfg.get('width'),cfg.get('height'))!=(w,h):raise ValueError('Semantic dimensions mismatch')
 used=np.zeros((h,w),bool);units=[];names=set()
 for u in cfg['units']:
  if not u.get('id') or u['id'] in names:raise ValueError('Unique semantic IDs required')
  names.add(u['id']);mask=np.array(Image.open(base/u['mask']).convert('L'))>127
  if mask.shape!=(h,w):raise ValueError('Semantic mask size mismatch')
  if np.any(mask&used):raise ValueError('Semantic masks overlap')
  mask &= rgba[:,:,3]>0
  if not mask.any():continue
  used|=mask;units.append((u,mask))
 if len(units)>max_shapes:raise ValueError('Budget cannot preserve one shape per semantic unit')
 # Semantic masks protect pale foreground, including nuclei and membranes.
 bg=background(rgb,cfg,base,used,rgba[:,:,3]);records=[];stage={}
 stage['semantic_units']=len(units)
 for u,mask in units:
  grid,colors=palette(rgb,mask,max(1,min(int(u.get('colors',6)),32)))
  grid,colors=adjacent_merge(grid,colors)
  records.append({'id':u['id'],'mask':mask,'grid':grid,'colors':colors,'protected':u.get('protected',False)})
 def count():
  total=0
  for r in records:
   n=len(np.unique(r['grid'][r['grid']>=0]));total+=n+(1 if n>1 else 0)
  return total
 stage['after_adjacent_color_merge']=count()
 # Stage 2: intra-object palette reduction preserves the largest main color.
 while count()>max_shapes:
  candidates=[]
  for r in records:
   ids,areas=np.unique(r['grid'][r['grid']>=0],return_counts=True)
   if len(ids)>2 and not r['protected']:
    for c,area in zip(ids,areas):
     if area<areas.max():candidates.append((area,r,c,ids))
  if not candidates:break
  _,r,c,ids=min(candidates,key=lambda p:p[0]);others=ids[ids!=c]
  dest=min(others,key=lambda d:np.linalg.norm(r['colors'][d]-r['colors'][c]))
  r['grid'][r['grid']==c]=dest
 stage['after_group_palette_merge']=count()
 if count()>max_shapes:
  for r in records:
   if not r['protected']:r['grid']=absorb_small(r['grid'])
 stage['after_small_island_absorption']=count()
 # Stage 4 never merges semantic objects or deletes a dominant body to force pass.
 while count()>max_shapes:
  candidates=[]
  for r in records:
   ids,areas=np.unique(r['grid'][r['grid']>=0],return_counts=True)
   if len(ids)>1 and not r['protected']:
    c=ids[np.argmin(areas)];candidates.append((int(areas.min()),r,c,ids))
  if not candidates:raise ValueError('Budget conflicts with protected semantic bodies')
  _,r,c,ids=min(candidates,key=lambda p:p[0]);dest=min(ids[ids!=c],key=lambda d:np.linalg.norm(r['colors'][d]-r['colors'][c]))
  r['grid'][r['grid']==c]=dest
 stage['after_smallest_color_absorption']=count()
 groups=[]
 for r in records:
  paths=contours(r['grid'],r['colors'],cfg.get('supersample',3))
  if len(paths)>1:
   # A real semantic body, counted against the same budget, covers antialiased internal seams.
   ids,areas=np.unique(r['grid'][r['grid']>=0],return_counts=True)
   color=r['colors'][ids[np.argmax(areas)]]
   boundary=smooth_contours(r['mask'],cfg.get('supersample',3))
   paths.insert(0,{'fill':'#'+''.join(f'{int(round(v)):02X}' for v in color),'contours':boundary,'commands':curve_commands(boundary)})
  groups.append({'id':r['id'],'paths':paths,'source_area':int(r['mask'].sum())})
 if any(not g['paths'] for g in groups):raise ValueError('A semantic unit lost all renderable geometry')
 shapes=sum(len(g['paths']) for g in groups);subs=sum(len(p['contours']) for g in groups for p in g['paths'])
 assert shapes<=max_shapes
 svg=ET.Element('svg',xmlns=S,width=str(w),height=str(h),viewBox=f'0 0 {w} {h}')
 for g in groups:
  ge=ET.SubElement(svg,'g',id=g['id'])
  for i,p in enumerate(g['paths']):
   d=' '.join(c[0]+' '.join(f'{v:.1f}' for v in c[1:]) for c in p['commands'])
   ET.SubElement(ge,'path',id=f'{g["id"]}-color-{i+1}',fill=p['fill'],d=d,stroke=p['fill'],attrib={'stroke-width':'1','stroke-linejoin':'round'})
 out.mkdir(parents=True)
 ET.ElementTree(svg).write(out/'graphics.svg',encoding='utf-8',xml_declaration=True)
 save_json(out/'groups.json',compact(groups,w,h))
 Image.fromarray(bg.astype('uint8')*255).save(out/'background-mask.png')
 Image.fromarray(used.astype('uint8')*255).save(out/'foreground-mask.png')
 audit={'vector_shapes':shapes,'subpaths':subs,'nodes':sum((len(c)-1)//2 for g in groups for p in g['paths'] for c in p['commands']),'groups':len(groups),'background_vector_shapes':0,'max_shapes':max_shapes,'stage_counts':stage,'foreground_pixels':int(used.sum()),'flood_background_pixels':int(bg.sum()),'unassigned_pixels':int((~bg&~used).sum()),'semantic_recognition':'reviewed input masks; not inferred by this tool','visual_acceptance':'pending render and review','source_sha256':hashlib.sha256(Path(image).read_bytes()).hexdigest()}
 audit.update(plan_id=proposal['plan'],supersample=cfg.get('supersample',3),coordinate_grid=.5,staircase_candidates=sum(staircase_candidates(p['commands']) for g in groups for p in g['paths']),edge_400_percent='pending actual 4x render review')
 save_json(out/'budget.json',audit);return audit

def el(parent,ns,tag,**attrs):return ET.SubElement(parent,f'{{{ns}}}{tag}',{k:str(v) for k,v in attrs.items()})

def audit(file):
 """Recount final package leaves independently of all build reports."""
 with zipfile.ZipFile(file) as z:
  if any(n.startswith('ppt/media/') for n in z.namelist()):raise ValueError('Raster/media package part found')
  result={'vector_shapes':0,'text_boxes':0,'groups':0,'subpaths':0,'nodes':0,'raster_objects':0}
  for name in z.namelist():
   if name.endswith('.rels'):
    if any(e.get('TargetMode')=='External' for e in ET.fromstring(z.read(name))):raise ValueError('External relationship found')
   if not(name.startswith('ppt/slides/slide') and name.endswith('.xml')):continue
   root=ET.fromstring(z.read(name))
   if root.findall('.//p:pic',NS) or root.findall('.//a:blip',NS) or root.findall('.//p:graphicFrame',NS):raise ValueError('Non-native graphic object found')
   if root.find('p:cSld/p:bg',NS) is not None:raise ValueError('Explicit slide background found')
   result['groups']+=len(root.findall('.//p:grpSp',NS))
   ids=[]
   for sp in root.findall('.//p:sp',NS):
    ids.append(sp.find('p:nvSpPr/p:cNvPr',NS).get('id'))
    text=''.join(t.text or '' for t in sp.findall('.//a:t',NS))
    geom=sp.find('p:spPr/a:custGeom',NS)
    if text and geom is None:result['text_boxes']+=1
    else:result['vector_shapes']+=max(1,len(sp.findall('p:spPr/a:custGeom/a:pathLst/a:path',NS)))
   if len(ids)!=len(set(ids)):raise ValueError('Duplicate native shape IDs')
   result['subpaths']+=len(root.findall('.//a:moveTo',NS));result['nodes']+=len(root.findall('.//a:pt',NS))
  if result['vector_shapes']>1000:raise ValueError(f"Hard budget exceeded: {result['vector_shapes']} > 1000")
  result.update(budget_pass=True,file_bytes=Path(file).stat().st_size,visual_acceptance='not established by structural audit')
  return result

def pptx(template,folder,output):
 folder=Path(folder);output=Path(output)
 if output.exists():raise ValueError('Output exists')
 data=expand(load_json(folder/'groups.json'));w,h=data['width'],data['height'];uid=100
 if not isinstance(w,int) or not isinstance(h,int) or min(w,h)<=0:raise ValueError('Invalid canvas dimensions')
 names=set();npaths=0
 for g in data['groups']:
  if not g.get('id') or g['id'] in names:raise ValueError('Duplicate/missing group ID')
  names.add(g['id'])
  if not g.get('paths'):raise ValueError('Empty group')
  for path in g['paths']:
   npaths+=1
   if not path.get('contours'):raise ValueError('Empty path')
   for c in path['contours']:
    coords=np.asarray(c,dtype=float)
    if coords.ndim!=2 or coords.shape[1]!=2 or len(coords)<3 or not np.isfinite(coords).all():raise ValueError('Invalid contour')
    if np.any(coords[:,0]<-.5) or np.any(coords[:,1]<-.5) or np.any(coords[:,0]>w) or np.any(coords[:,1]>h):raise ValueError('Contour out of bounds')
 if npaths>1000:raise ValueError('PPTX exceeds hard budget of 1000 graphic shapes')
 ET.register_namespace('a',A);ET.register_namespace('p',P)
 with zipfile.ZipFile(template) as z:
  pr=ET.fromstring(z.read('ppt/presentation.xml'));size=pr.find('p:sldSz',NS)
  if size is None or (int(size.get('cx')),int(size.get('cy')))!=(w*9525,h*9525):raise ValueError('Template canvas size mismatch')
  root=ET.fromstring(z.read('ppt/slides/slide1.xml'));tree=root.find('p:cSld/p:spTree',NS)
  if tree.findall('p:grpSp//p:txBody',NS):raise ValueError('Nested text template requires transform normalization')
  texts=[copy.deepcopy(s) for s in tree.findall('.//p:sp',NS) if s.find('p:txBody',NS) is not None]
  if any(s.find('p:spPr/a:custGeom',NS) is not None or s.find('p:spPr/a:solidFill',NS) is not None or s.find('p:spPr/a:gradFill',NS) is not None for s in texts):raise ValueError('Use plain unfilled text boxes in template')
  for child in list(tree):
   if child.tag not in (f'{{{P}}}nvGrpSpPr',f'{{{P}}}grpSpPr'):tree.remove(child)
  slidebg=root.find('p:cSld/p:bg',NS)
  if slidebg is not None:root.find('p:cSld',NS).remove(slidebg)
  for g in data['groups']:
   group=el(tree,P,'grpSp');nv=el(group,P,'nvGrpSpPr');el(nv,P,'cNvPr',id=uid,name=g['id']);uid+=1;el(nv,P,'cNvGrpSpPr');el(nv,P,'nvPr')
   gp=el(group,P,'grpSpPr');xf=el(gp,A,'xfrm')
   # Tight group bounds allow meaningful selection and resizing.
   pts=np.array([pt for path in g['paths'] for c in path['contours'] for pt in c]);lo=pts.min(0);hi=pts.max(0)+1
   for tag,attrs in [('off',dict(x=round(lo[0]*9525),y=round(lo[1]*9525))),('ext',dict(cx=round((hi[0]-lo[0])*9525),cy=round((hi[1]-lo[1])*9525))),('chOff',dict(x=round(lo[0]*9525),y=round(lo[1]*9525))),('chExt',dict(cx=round((hi[0]-lo[0])*9525),cy=round((hi[1]-lo[1])*9525)))]:el(xf,A,tag,**attrs)
   for i,path in enumerate(g['paths']):
    sp=el(group,P,'sp');nv=el(sp,P,'nvSpPr');el(nv,P,'cNvPr',id=uid,name=f'{g["id"]}-color-{i+1}');uid+=1;el(nv,P,'cNvSpPr');el(nv,P,'nvPr')
    props=el(sp,P,'spPr');xf=el(props,A,'xfrm');el(xf,A,'off',x=0,y=0);el(xf,A,'ext',cx=w*9525,cy=h*9525)
    geo=el(props,A,'custGeom');pl=el(geo,A,'pathLst');pa=el(pl,A,'path',w=w*100,h=h*100)
    if path.get('commands'):
     for command in path['commands']:
      op=command[0]
      node=el(pa,A,{'M':'moveTo','L':'lnTo','C':'cubicBezTo','Z':'close'}[op])
      for i in range(1,len(command),2):el(node,A,'pt',x=round(command[i]*100),y=round(command[i+1]*100))
    else:
     for contour in path['contours']:
      for j,(x,y) in enumerate(contour):el(el(pa,A,'moveTo' if j==0 else 'lnTo'),A,'pt',x=round(x*100),y=round(y*100))
      el(pa,A,'close')
    el(el(props,A,'solidFill'),A,'srgbClr',val=path['fill'][1:])
    line=el(props,A,'ln',w=9525);el(el(line,A,'solidFill'),A,'srgbClr',val=path['fill'][1:]);el(line,A,'round')
  for s in texts:
   s.find('p:nvSpPr/p:cNvPr',NS).set('id',str(uid));uid+=1;tree.append(s)
  # A template may contain other slides/media; this tool intentionally rejects them.
  if len([n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')])!=1:raise ValueError('Use a single-slide text template')
  if any(n.startswith('ppt/media/') for n in z.namelist()):raise ValueError('Template contains media; use a native-only template')
  with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as out:
   for item in z.infolist():out.writestr(item,ET.tostring(root,encoding='utf-8',xml_declaration=True) if item.filename=='ppt/slides/slide1.xml' else z.read(item.filename))
 check=audit(output)
 return dict(check,pptx=str(output))

def main():
 parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
 b=commands.add_parser('build');b.add_argument('image');b.add_argument('semantic');b.add_argument('output');b.add_argument('--max-shapes',type=int,default=1000);b.add_argument('--confirm-plan',required=True)
 q=commands.add_parser('plan');q.add_argument('image');q.add_argument('semantic');q.add_argument('--max-shapes',type=int,default=1000)
 p=commands.add_parser('pptx');p.add_argument('template');p.add_argument('folder');p.add_argument('output')
 a=commands.add_parser('audit');a.add_argument('file')
 args=parser.parse_args()
 if args.command=='plan':result=plan(args.image,args.semantic,args.max_shapes)
 elif args.command=='build':result=build(args.image,args.semantic,args.output,args.max_shapes,args.confirm_plan)
 elif args.command=='pptx':result=pptx(args.template,args.folder,args.output)
 else:result=audit(args.file)
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,KeyError,zipfile.BadZipFile) as error:
  print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False),file=sys.stderr)
  sys.exit(1)
