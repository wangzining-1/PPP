import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
const args=process.argv.slice(2);
if(args.length===1 && ['--help','-h'].includes(args[0])) {
  console.log('render <saved.pptx> <new-preview.png> [--scale 4]: reimport and render slide 1.');
} else {
  try {
    if(args.length!==2 && !(args.length===4 && args[2]==='--scale')) throw new Error('Usage: render <saved.pptx> <new-preview.png> [--scale 4]');
    const scale=args.length===4 ? Number(args[3]):1;
    if(![1,2,3,4].includes(scale))throw new Error('Scale must be 1, 2, 3 or 4');
    try {await fs.access(args[1]);throw new Error('Output exists');} catch(e){if(e.code!=='ENOENT')throw e;}
    const config=JSON.parse((await fs.readFile(path.join(path.dirname(fileURLToPath(import.meta.url)),'../runtime.local.json'),'utf8')).replace(/^\uFEFF/,''));
    const require=createRequire(path.join(config.node_modules,'__ppp_render__.cjs'));
    const {PresentationFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
    const deck=await PresentationFile.importPptx(await FileBlob.load(args[0]));
    if(deck.slides.items.length!==1)throw new Error('Single-slide diagram required');
    const png=await deck.export({slide:deck.slides.items[0],format:'png',scale});
    await fs.writeFile(args[1],new Uint8Array(await png.arrayBuffer()));
    console.log(JSON.stringify({input:args[0],preview:args[1],renderer:'Artifact Tool reimport',powerpointDesktopVerified:false}));
  } catch(e){console.error(e.message);process.exitCode=1;}
}
