import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(path.join(path.resolve(process.env.RUNTIME_NODE_MODULES),'__ppp__.cjs'));
const tool=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
require('jszip');
if(!tool.Presentation || !tool.PresentationFile) throw new Error('Presentation API unavailable');
console.log(JSON.stringify({node:process.version,artifact_tool:true,jszip:true}));
