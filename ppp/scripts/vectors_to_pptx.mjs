// Export geometry.json as native PowerPoint shapes, never as an embedded image.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [input, output] = process.argv.slice(2);
if (!input || !output || !process.env.RUNTIME_NODE_MODULES) {
  throw new Error('Usage: node vectors_to_pptx.mjs geometry.json new.pptx; set RUNTIME_NODE_MODULES');
}
try { await fs.access(output); throw new Error('Output exists; choose a new PPTX path'); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
const require = createRequire(path.join(path.resolve(process.env.RUNTIME_NODE_MODULES), '__ppp__.cjs'));
const { Presentation, PresentationFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const data = JSON.parse(await fs.readFile(input, 'utf8'));
if (data.schema !== 'ppp.rectangles.v1' || !Number.isInteger(data.width) ||
    !Number.isInteger(data.height) || data.width < 1 || data.height < 1 ||
    !Array.isArray(data.rectangles) || data.shape_count !== data.rectangles.length) {
  throw new Error('Invalid PPP geometry');
}
const scale = 960 / Math.max(data.width, data.height);
const presentation = Presentation.create({ slideSize: { width: data.width * scale, height: data.height * scale } });
const slide = presentation.slides.add();
slide.background.fill = '#FFFFFF';
for (const [index, cell] of data.rectangles.entries()) {
  const [x, y, width, height, rgba] = cell;
  if (![x, y, width, height].every(Number.isInteger) || x < 0 || y < 0 ||
      width < 1 || height < 1 || x + width > data.width || y + height > data.height ||
      !Array.isArray(rgba) || rgba.length !== 4 ||
      !rgba.every(c => Number.isInteger(c) && c >= 0 && c <= 255)) throw new Error('Invalid rectangle');
  const [r, g, b, a] = rgba;
  const hex = [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
  slide.shapes.add({
    name: `PPP-${index + 1}`, geometry: 'rect',
    position: { left: x * scale, top: y * scale, width: width * scale, height: height * scale },
    fill: { type: 'solid', color: { type: 'rgb', value: hex, transform: { opacity: a / 255 } } },
    line: { fill: 'none', width: 0 },
  });
}
await fs.mkdir(path.dirname(path.resolve(output)), { recursive: true });
await (await PresentationFile.exportPptx(presentation)).save(output);
console.log(JSON.stringify({ output, shapes: data.shape_count, status: 'draft; PPTX rendering still requires verification' }));
