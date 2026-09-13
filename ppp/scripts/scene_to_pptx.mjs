#!/usr/bin/env node
// Semantic scene -> native shapes/text. Cubic geometry is patched into DrawingML.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const renderIndex = args.indexOf('--render');
let renderOutput;
if (renderIndex >= 0) { renderOutput = args[renderIndex+1]; if(!renderOutput) throw new Error('--render needs a PNG path'); args.splice(renderIndex,2); }
if (args.includes('--help') || args.includes('-h')) {
  console.log('Usage: node scene_to_pptx.mjs scene.json new.pptx [new.svg] [--render new.png]\nSet RUNTIME_NODE_MODULES to bundled node_modules. Outputs must not exist. Schema: references/scene-schema.md');
  process.exit(0);
}
const [input, output, svgOutput = output?.replace(/\.pptx$/i, '') + '.svg'] = args;
const fail = msg => { throw new Error(msg); };
const num = (v, label) => Number.isFinite(v) ? v : fail(`Invalid ${label}`);
const positive = (v, label) => num(v, label) > 0 ? v : fail(`${label} must be positive`);
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const color = (v = 'none') => /^(none|#[0-9a-f]{6})$/i.test(v) ? v : fail(`Unsupported color ${v}`);
const alpha = (v = 1) => num(v, 'opacity') >= 0 && v <= 1 ? v : fail('Opacity outside 0..1');
const keysOnly = (value, keys, label) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${label} must be an object`);
  const allowed = new Set(keys);
  for (const key of Object.keys(value)) if (!allowed.has(key)) fail(`Unsupported ${label} field ${key}; flatten supported geometry first or put non-rendering information in metadata`);
  if ('metadata' in value && (!value.metadata || typeof value.metadata !== 'object' || Array.isArray(value.metadata))) fail(`${label}.metadata must be an object`);
};
if (!input || !output || args.length > 3) fail('Use --help for usage');
if (!process.env.RUNTIME_NODE_MODULES) fail('Set RUNTIME_NODE_MODULES');
if (path.resolve(output) === path.resolve(svgOutput)) fail('Outputs must differ');
if (renderOutput && [output,svgOutput].some(p=>path.resolve(p)===path.resolve(renderOutput))) fail('Outputs must differ');
for (const file of [output, svgOutput, renderOutput].filter(Boolean)) {
  try { await fs.access(file); fail(`Output exists: ${file}`); }
  catch (e) { if (e.code !== 'ENOENT') throw e; }
}
const data = JSON.parse((await fs.readFile(input, 'utf8')).replace(/^\uFEFF/, ''));
keysOnly(data,['version','width','height','background','elements','metadata'],'scene');
if (data.version !== 1 || !Array.isArray(data.elements)) fail('Expected scene version 1 and elements');
positive(data.width, 'width'); positive(data.height, 'height');
const ids = new Set();
for (const e of data.elements) {
  const common=['id','type','fill','stroke','strokeWidth','opacity','fillOpacity','strokeOpacity','metadata'];
  const specific={path:['commands','fillRule'],line:['x1','y1','x2','y2','arrowStart','arrowEnd'],rect:['x','y','width','height'],ellipse:['x','y','width','height'],text:['x','y','width','height','text','fontFamily','fontSize','bold','italic','align']};
  if(!e || !specific[e.type]) fail(`Unsupported type ${e?.type}`);
  keysOnly(e,[...common,...specific[e.type]],`element ${e.id??''}`);
  if (typeof e.id !== 'string' || !/^[A-Za-z_][\w.-]*$/.test(e.id) || ids.has(e.id)) fail('IDs must be unique XML-safe names');
  ids.add(e.id);
  if (!['path','text','rect','ellipse','line'].includes(e.type)) fail(`Unsupported type ${e.type}`);
  color(e.fill); color(e.stroke); alpha(e.opacity); alpha(e.fillOpacity); alpha(e.strokeOpacity);
  if (e.strokeWidth !== undefined && num(e.strokeWidth, 'strokeWidth') < 0) fail('Negative stroke width');
  if (e.fillRule && e.fillRule !== 'nonzero') fail('Only nonzero fillRule supported; orient hole contours oppositely');
  if (e.type === 'path') {
    if (!e.commands?.length || e.commands[0].op !== 'M') fail(`Path ${e.id} must start with M`);
    if (!Array.isArray(e.commands) || e.commands.length > 100000) fail(`Path ${e.id} exceeds 100000 command budget`);
    for (const c of e.commands) {
      const fields = {M:['x','y'],L:['x','y'],C:['x1','y1','x2','y2','x','y'],Z:[]}[c.op];
      if (!fields) fail(`Unsupported path command ${c.op}`);
      keysOnly(c,['op',...fields],`path command ${c.op}`);
      fields.forEach(k => num(c[k], `${e.id}.${k}`));
    }
  } else if (e.type === 'line') {
    ['x1','y1','x2','y2'].forEach(k => num(e[k], k));
    for (const k of ['arrowStart','arrowEnd']) if (e[k] && e[k] !== 'triangle') fail('Only triangle arrow ends supported');
  } else {
    num(e.x,'x'); num(e.y,'y'); positive(e.width,'width'); positive(e.height,'height');
    if (e.type === 'text') {
      if(e.stroke && e.stroke !== 'none') fail('Text outline unsupported; use plain editable text');
      if (typeof e.text !== 'string') fail('Text must be a string');
      positive(e.fontSize ?? 16,'fontSize');
      if(e.fontFamily!==undefined && (typeof e.fontFamily!=='string'||!e.fontFamily.trim())) fail('Invalid fontFamily');
      for(const key of ['bold','italic']) if(e[key]!==undefined&&typeof e[key]!=='boolean') fail(`${key} must be boolean`);
      if (e.align && !['left','center','right'].includes(e.align)) fail('Invalid alignment');
    }
  }
}
const require = createRequire(path.join(path.resolve(process.env.RUNTIME_NODE_MODULES), '__ppp__.cjs'));
const { Presentation, PresentationFile, FileBlob } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const JSZip = require('jszip');
const scale = Math.min(1, 1920 / Math.max(data.width, data.height));
const deck = Presentation.create({slideSize:{width:data.width*scale,height:data.height*scale}});
const slide = deck.slides.add(); slide.background.fill = color(data.background ?? '#FFFFFF');
const fill = (c, a) => c === 'none' ? 'none' : {type:'solid',color:{type:'rgb',value:c.slice(1),transform:{opacity:a}}};
const patch = new Map();
const svg = [];
for (const e of data.elements) {
  const opacity = alpha(e.opacity), fc = color(e.fill ?? (e.type === 'text' ? '#000000' : 'none'));
  const sc = color(e.stroke), fa = opacity*alpha(e.fillOpacity), sa = opacity*alpha(e.strokeOpacity);
  const sw = e.strokeWidth ?? 1;
  let b = {x:e.x,y:e.y,width:e.width,height:e.height};
  let commands = e.commands;
  if (e.type === 'line') commands = [{op:'M',x:e.x1,y:e.y1},{op:'L',x:e.x2,y:e.y2}];
  if (commands) {
    let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
    for (const c of commands) for (const suffix of ['', '1', '2']) if (c['x'+suffix] !== undefined) {
      minX=Math.min(minX,c['x'+suffix]);maxX=Math.max(maxX,c['x'+suffix]);
      minY=Math.min(minY,c['y'+suffix]);maxY=Math.max(maxY,c['y'+suffix]);
    }
    b = {x:minX,y:minY,width:Math.max(0.01,maxX-minX),height:Math.max(0.01,maxY-minY)};
  }
  const cfg = {name:e.id, geometry:commands ? 'custom' : e.type === 'text' ? 'textbox' : e.type,
    position:{left:b.x*scale,top:b.y*scale,width:b.width*scale,height:b.height*scale},
    fill:e.type === 'text' ? 'none' : fill(fc,fa),line:{fill:fill(sc,sa),width:sw*scale}};
  if(commands) cfg.customPaths=[{width:b.width,height:b.height,commands:[{moveTo:{x:0,y:0}},{lineTo:{x:b.width,y:b.height}}]}];
  const shape = slide.shapes.add(cfg);
  if(e.type === 'text') {
    shape.text=e.text;
    shape.text.style={fontSize:(e.fontSize??16)*scale,typeface:e.fontFamily??'Arial',bold:!!e.bold,italic:!!e.italic,
      fill:fill(fc,fa),alignment:e.align??'left',verticalAlignment:'top',autoFit:'none',wrap:'none',insets:{left:0,right:0,top:0,bottom:0}};
  }
  if(commands) {
    const pt=(x,y)=>`<a:pt x="${Math.round((x-b.x)*9525*scale)}" y="${Math.round((y-b.y)*9525*scale)}"/>`;
    const xml=commands.map(c=>c.op==='Z'?'<a:close/>':c.op==='C'?`<a:cubicBezTo>${pt(c.x1,c.y1)}${pt(c.x2,c.y2)}${pt(c.x,c.y)}</a:cubicBezTo>`:`<a:${c.op==='M'?'moveTo':'lnTo'}>${pt(c.x,c.y)}</a:${c.op==='M'?'moveTo':'lnTo'}>`).join('');
    patch.set(e.id,{geometry:`<a:pathLst><a:path w="${Math.round(b.width*9525*scale)}" h="${Math.round(b.height*9525*scale)}">${xml}</a:path></a:pathLst>`,e});
  }
  const attr=`id="${esc(e.id)}" fill="${fc}" fill-opacity="${fa}" stroke="${sc}" stroke-opacity="${sa}" stroke-width="${sw}"`;
  if(commands) {
    const d=commands.map(c=>c.op==='Z'?'Z':c.op==='C'?`C${c.x1},${c.y1} ${c.x2},${c.y2} ${c.x},${c.y}`:`${c.op}${c.x},${c.y}`).join(' ');
    let markers='';
    for (const [key,side] of [['arrowStart','start'],['arrowEnd','end']]) if(e[key]) {
      const id=e.id+'-'+side;
      svg.push(`<defs><marker id="${id}" viewBox="0 0 6 6" refX="6" refY="3" markerWidth="3" markerHeight="3" orient="auto-start-reverse"><path d="M0 0 L6 3 L0 6 Z" fill="${sc}" fill-opacity="${sa}"/></marker></defs>`);
      markers+=` marker-${side}="url(#${id})"`;
    }
    svg.push(`<path ${attr} fill-rule="nonzero" d="${d}"${markers}/>`);
  } else if(e.type==='rect') svg.push(`<rect ${attr} x="${e.x}" y="${e.y}" width="${e.width}" height="${e.height}"/>`);
  else if(e.type==='ellipse') svg.push(`<ellipse ${attr} cx="${e.x+e.width/2}" cy="${e.y+e.height/2}" rx="${e.width/2}" ry="${e.height/2}"/>`);
  else {
    const align=e.align??'left',x=e.x+(align==='center'?e.width/2:align==='right'?e.width:0),size=e.fontSize??16;
    svg.push(`<text ${attr} x="${x}" y="${e.y}" dominant-baseline="text-before-edge" text-anchor="${{left:'start',center:'middle',right:'end'}[align]}" font-family="${esc(e.fontFamily??'Arial')}" font-size="${size}" font-weight="${e.bold?'bold':'normal'}" font-style="${e.italic?'italic':'normal'}">${e.text.split('\n').map((t,i)=>`<tspan x="${x}" dy="${i?size*1.2:0}">${esc(t)}</tspan>`).join('')}</text>`);
  }
}
await fs.mkdir(path.dirname(path.resolve(output)),{recursive:true});
await fs.mkdir(path.dirname(path.resolve(svgOutput)),{recursive:true});
// Export temporary PPTX; patch only native path commands missing from public API.
const temp=output+`.${process.pid}.tmp`;
try {
  await (await PresentationFile.exportPptx(deck)).save(temp);
  const zip=await JSZip.loadAsync(await fs.readFile(temp));
  let xml=await zip.file('ppt/slides/slide1.xml').async('string');
  let patched=0;
  xml=xml.replace(/<p:sp\b[\s\S]*?<\/p:sp>/g, block=>{
    const name=block.match(/<p:cNvPr\b[^>]*\bname="([^"]*)"/)?.[1], entry=patch.get(name);
    if(!entry)return block;
    if(!/<a:pathLst>/.test(block))fail(`Missing custom path for ${name}`);
    patched++;
    block=block.replace(/<a:pathLst>[\s\S]*?<\/a:pathLst>/,entry.geometry);
    for(const [key,tag] of [['arrowStart','headEnd'],['arrowEnd','tailEnd']]) if(entry.e[key]) block=block.replace('</a:ln>',`<a:${tag} type="triangle" w="med" len="med"/></a:ln>`);
    return block;
  });
  if(patched!==patch.size)fail('Native path patch count mismatch');
  if(/<p:pic\b|<a:blip\b/.test(xml))fail('Unexpected picture object');
  // Artifact Tool emits p:bg with a:noFill for 'none'; honor the scene contract
  // by omitting the explicit slide background, as the budget auditor requires.
  if (data.background === 'none') xml = xml.replace(/<p:bg\b[^>]*>[\s\S]*?<\/p:bg>/g, '');
  zip.file('ppt/slides/slide1.xml',xml);
  await fs.writeFile(output,await zip.generateAsync({type:'nodebuffer',compression:'DEFLATE'}),{flag:'wx'});
  const background=data.background??'#FFFFFF';
  const bg=background!=='none'?`<rect width="100%" height="100%" fill="${color(background)}"/>`:'';
  await fs.writeFile(svgOutput,`<svg xmlns="http://www.w3.org/2000/svg" width="${data.width}" height="${data.height}" viewBox="0 0 ${data.width} ${data.height}">${bg}${svg.join('\n')}</svg>`,{flag:'wx'});
  if(renderOutput) {
    const imported = await PresentationFile.importPptx(await FileBlob.load(output));
    const rendered = await imported.export({slide:imported.slides.items[0],format:'png',scale:1/scale});
    await fs.mkdir(path.dirname(path.resolve(renderOutput)),{recursive:true});
    await fs.writeFile(renderOutput,new Uint8Array(await rendered.arrayBuffer()),{flag:'wx'});
  }
  console.log(JSON.stringify({pptx:output,svg:svgOutput,objects:data.elements.length,cubicPaths:patch.size,status:'native XML exported; render and compare final PPTX before acceptance'}));
} finally { await fs.rm(temp,{force:true}); await fs.rm(temp+'.inspect.ndjson',{force:true}); }
