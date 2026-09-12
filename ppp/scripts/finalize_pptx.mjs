#!/usr/bin/env node
// Finalize an existing native PPTX through the installed Presentations validators.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const usage = 'Usage: finalize_pptx.mjs <workspace> <candidate.pptx> <new-final.pptx> [--config <runtime.local.json>]\nCandidate and final must be inside workspace. Put final in a dedicated output subdirectory. Existing outputs are never overwritten.';
const argv = process.argv.slice(2);
if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) {
  console.log(usage);
  process.exit(0);
}
const fail = message => { throw new Error(message); };
async function absent(file) {
  try { await fs.lstat(file); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  fail(`Output exists: ${file}`);
}
function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative !== '' && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}

try {
  if (![3, 5].includes(argv.length) || argv.slice(0, 3).some(v => v.startsWith('--')) ||
      (argv.length === 5 && (argv[3] !== '--config' || argv[4].startsWith('--')))) fail(usage);
  const [workspaceArg, candidateArg, finalArg] = argv;
  const workspace = await fs.realpath(path.resolve(workspaceArg));
  const candidate = await fs.realpath(path.resolve(candidateArg));
  const final = path.resolve(finalArg);
  if (!inside(workspace, candidate) || !inside(workspace, final)) fail('Candidate and final must stay inside workspace');
  if (![candidate, final].every(p => p.toLowerCase().endsWith('.pptx'))) fail('Candidate and final must use .pptx');
  if (path.dirname(final) === workspace) fail('Final must use a dedicated output subdirectory so validation receipts remain private');
  const privateDir = path.join(workspace, '.ppp-validation');
  if (inside(privateDir, final) || path.dirname(final) === privateDir) fail('Final cannot be inside the private validation directory');
  const receipt = path.join(privateDir, path.basename(final) + '.json');
  await absent(final);
  await absent(receipt);
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const configPath = path.resolve(argv[4] ?? path.join(scriptDir, '..', 'runtime.local.json'));
  const config = JSON.parse((await fs.readFile(configPath, 'utf8')).replace(/^\uFEFF/, ''));
  for (const key of ['python', 'node_modules', 'presentation_skill']) {
    if (typeof config[key] !== 'string' || !path.isAbsolute(config[key])) fail(`Config needs absolute ${key}`);
    await fs.access(config[key]);
  }
  const presentationPython = config.presentation_python ?? config.python;
  if (typeof presentationPython !== 'string' || !path.isAbsolute(presentationPython)) fail('Config needs absolute presentation_python');
  await fs.access(presentationPython);
  process.env.RUNTIME_NODE_MODULES = config.node_modules;
  process.env.PYTHONDONTWRITEBYTECODE = '1';
  const require = createRequire(path.join(config.node_modules, '__ppp_finalizer__.cjs'));
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(await fs.readFile(candidate));
  const presentationPart = zip.file('ppt/presentation.xml');
  if (!presentationPart) fail('Candidate is missing ppt/presentation.xml');
  const xml = await presentationPart.async('string');
  const sizeTag = xml.match(/<(?:[A-Za-z_][\w.-]*:)?sldSz\b[^>]*\/?\s*>/)?.[0];
  const cx = sizeTag?.match(/\bcx=["'](\d+)["']/)?.[1];
  const cy = sizeTag?.match(/\bcy=["'](\d+)["']/)?.[1];
  if (!cx || !cy || Number(cx) <= 0 || Number(cy) <= 0) fail('Candidate has invalid slide dimensions');
  const helpers = path.join(config.presentation_skill, 'container_tools');
  const { finalizePresentation } = await import(pathToFileURL(path.join(helpers, 'artifact_tool_utils.mjs')).href);
  // Check the nearest existing ancestors before creating output directories.
  for (const directory of [path.dirname(final), privateDir]) {
    let existing = directory;
    while (true) {
      try {
        const real = await fs.realpath(existing);
        if (real !== workspace && !inside(workspace, real)) fail('Output directory escapes workspace through a link');
        break;
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
        existing = path.dirname(existing);
      }
    }
  }
  await fs.mkdir(path.dirname(final), { recursive: true });
  await fs.mkdir(privateDir, { recursive: true });
  const result = await finalizePresentation({
    workspaceDir: workspace, candidatePath: candidate, finalPath: final,
    pythonExecutable: presentationPython,
    integrityValidatorPath: path.join(helpers, 'inspect_presentation_package_integrity.py'),
    layoutValidatorPath: path.join(helpers, 'inspect_presentation_layout_geometry.py'),
    layoutArgs: ['--expected-slide-size-emu', `${cx},${cy}`, '--validate-bullet-geometry', '--validate-heading-fit'],
    verifyArtifactToolImport: true, receiptPath: receipt,
  });
  console.log(JSON.stringify({ final: result.finalPath, receipt: result.receiptPath,
    sha256: result.finalSha256, status: 'package/layout/import validation passed; visual and PowerPoint application verification are separate' }));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
