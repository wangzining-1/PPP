# PPP semantic scene v1

`scene_to_pptx.mjs` compiles an already understood/repaired scene. It does not recognize raster content or recover missing scientific information. All visible elements become native PPT shapes or editable text, never bitmap/SVG picture objects. One scene creates one slide.

```json
{"version":1,"width":640,"height":360,"background":"#FFFFFF","elements":[
  {"id":"cell","type":"ellipse","x":30,"y":40,"width":170,"height":130,"fill":"#77CCAA","opacity":0.5,"stroke":"#225544","strokeWidth":2},
  {"id":"cell_label","type":"text","x":65,"y":88,"width":120,"height":35,"text":"Cell α","fontFamily":"Arial","fontSize":24,"fill":"#112233"},
  {"id":"signal","type":"line","x1":205,"y1":110,"x2":325,"y2":110,"stroke":"#333333","strokeWidth":3,"arrowEnd":"triangle"},
  {"id":"curve","type":"path","fill":"none","stroke":"#CC3344","strokeWidth":3,"commands":[{"op":"M","x":40,"y":240},{"op":"C","x1":100,"y1":175,"x2":190,"y2":330,"x":270,"y":230}]}
]}
```

## Coordinate and style contract

- All coordinates and font sizes are finite **pixels in the source canvas**, top-left origin, y down. Width/height must be positive. The exporter scales uniformly if the longest slide dimension exceeds 1920px. SVG retains source coordinates.
- `elements` order is back to front. Every element requires a unique stable `id` matching `[A-Za-z_][\w.-]*`; PPT selection-pane names preserve those IDs. Update an existing semantic ID across iterations instead of generating new IDs.
- Supported types: `rect`, `ellipse`, `text`, `line`, `path`. Rect/ellipse/text require `x,y,width,height`. Rectangle corners are square.
- `fill` and `stroke`: `#RRGGBB` or `none`. Default fill is none except black text. Default stroke is none. `strokeWidth` defaults to 1px and must be nonnegative. `opacity`, `fillOpacity`, `strokeOpacity` range 0..1; effective fill/stroke alpha is the product with `opacity`.
- `background` defaults to white. `none` produces no explicit SVG background and no PPT slide fill; presentation viewers may still display a white canvas. Validate transparency against explicit backgrounds; PPT slides are not transparent-image containers.

## Geometry and text

`path.commands` starts with `M`. Supported absolute commands are `{op:'M',x,y}`, `{op:'L',x,y}`, `{op:'C',x1,y1,x2,y2,x,y}`, `{op:'Z'}`. Cubics become native `a:cubicBezTo`, not sampled polylines. Paths use one compound DrawingML path and **nonzero winding**. Holes need opposite winding to the enclosing contour. `fillRule:'evenodd'` is rejected; convert winding first. Inspect nested holes, self intersections and touching contours visually. Paths use their control-point bounding box as local shape coordinates; all commands remain editable.

`line` requires `x1,y1,x2,y2`. Optional `arrowStart`/`arrowEnd` accept `triangle` only, exported as native line ends. Lines are geometric objects, not connectors attached to other shapes; moving a cell does not reroute the arrow automatically.

`text` requires string `text`. Optional `fontFamily` (Arial default), `fontSize` (16px default), `bold`, `italic`, `align` (`left`, `center`, `right`). `x,y` refer to the **top-left text frame, not the font baseline**. Text has zero insets, no auto-fit and no wrapping; insert explicit newlines and make the frame large enough. Font substitution, glyph ascent and newline spacing vary between SVG and PowerPoint. The SVG uses text-before-edge and 1.2× font-size line increments; always check the rendered final PPTX. Scientific subscripts/superscripts can be separately positioned text objects with stable IDs; mixed-run formatting is not yet supported by this schema. Text outlines are rejected.

Unsupported: arbitrary SVG strings, embedded images, gradients/patterns, clipping/masks, filters, rotation, dashes, groups, rich text runs, attached connectors, editable charts. Flatten transforms to coordinates, expand strokes or build explicit native geometry only when faithful; otherwise record the gap and extend the helper. Do not silently replace unsupported objects with a bitmap. Unknown scene/element/command keys are rejected, including unsupported rendering properties. Optional scene/element `metadata` objects accept arbitrary non-rendering information and have no rendering effect. Each path has a 100,000-command resource budget; split genuinely separate semantic parts or simplify within agreed fidelity limits when exceeded. Bounding-box calculation does not spread commands into function arguments.

## Run and verify

```powershell
$env:RUNTIME_NODE_MODULES = '<bundled node_modules returned by load_workspace_dependencies>'
& '<bundled node.exe>' '<skill>/scripts/scene_to_pptx.mjs' scene.json output.pptx output.svg --render final.png
```

Outputs must be new paths. `--help` needs no runtime configuration. Runtime uses bundled `@oai/artifact-tool` and `jszip`, located with `createRequire`; no installation into the shared bundle. The public shape API only documents straight custom paths, so the exporter patches native DrawingML cubic/compound commands after export. `--render` **imports the persisted patched PPTX** and renders it using Artifact Tool. This is not PowerPoint desktop verification. An unsuccessful render may leave the valid PPTX/SVG outputs for diagnosis; choose new output paths when retrying.

Test: `tests/scene_test.py` creates `.build/scene-tests`, asserts native shapes, stable names/order, editable text, cubic commands, two hole contours, opacity, arrow end and no media; then renders the saved PPTX. Review this PNG and compare with a source render. These tests establish this subset on the installed runtime, not arbitrary-image fidelity or every Office version.
