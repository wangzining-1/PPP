# SVG → editable scene

`scripts/svg_to_scene.py input.svg output.scene.json` uses `svgpathtools` for
path parsing and `svgelements` for affine transforms. The output is geometry,
not an SVG image inserted in a slide. Existing output files are never overwritten.

Supported subset:

- SVG dimensions and viewBox (`none` or default centered `meet` scaling).
- Nested groups and affine transforms; solid fills, opacity on individual objects,
  inherited presentation attributes and inline styles.
- Paths including relative coordinates, quadratic and cubic Béziers, elliptical
  arcs; rect/rounded rect, circle, ellipse, polygon, polyline and line.
- Nonzero compound paths retain contour direction, including holes. Export uses
  native DrawingML subpaths. No background-colored hole covers are added.
- Plain single-line text remains a text element. Positive uniform scale and
  translation are supported. SVG baseline becomes approximate top position
  `y - 0.8 * fontSize`; width estimates and font substitution require visual review.

Arc conversion uses cubic segments of at most 45 degrees. These approximate the
original ellipse. Quadratic-to-cubic conversion is exact. Native curve control
points remain editable after export.

Rejected with errors: images, external references, use/symbol, CSS stylesheets,
classes, unknown attributes/styles, gradients/patterns, masks/clips/filters,
group opacity, compound evenodd fill, stroke dashes/markers, non-default stroke
caps/joins, nonuniform/skewed stroked transforms, nested SVG viewports, text spans,
text-anchor other than start, text rotation, text stroke, and unsupported units.
Convert these explicitly into supported geometry or reconstruct them; there is
no bitmap fallback. The importer is a bounded geometry bridge, not a general SVG
renderer or an automatic semantic diagram understanding system.

Scene contract (`version: 1`): canvas `width`, `height`, ordered `elements`.
Path elements use `type: "path"`, `commands` with absolute `M`, `L`, `C`, `Z`;
`C` has `x1,y1,x2,y2,x,y`. Text uses `type: "text"`, `text`, top-left `x,y`,
`width,height,fontFamily,fontSize,bold,italic`. Both have `id`, `fill`, `stroke`,
`strokeWidth`, `opacity`, `fillOpacity`, `strokeOpacity`. Colors are `#RRGGBB` or
`none`. Font sizes and coordinates are SVG user units mapped to canvas pixels.

Verify with `python -m unittest discover -s tests -p test_svg_scene.py -v`.
The tests exercise geometry and explicit rejection. Actual exported PPTX visual
verification remains necessary, especially for holes, text and transformed strokes.
