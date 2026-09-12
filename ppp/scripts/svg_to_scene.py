"""Import a deliberately bounded SVG subset into editable PPP geometry."""
from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import ImageColor
from svgelements import Matrix
from svgpathtools import Arc, CubicBezier, Line, QuadraticBezier, parse_path


class UnsupportedSVG(ValueError):
    pass


NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
STYLE_KEYS = {'fill', 'stroke', 'stroke-width', 'fill-opacity', 'stroke-opacity',
              'opacity', 'fill-rule', 'font-family', 'font-size', 'font-weight',
              'font-style', 'text-anchor', 'display', 'visibility', 'color',
              'stroke-linecap', 'stroke-linejoin'}


def number(value, default=0):
    if value is None:
        return float(default)
    if not re.fullmatch(NUMBER + r'(?:px)?', value.strip()):
        raise UnsupportedSVG(f'Unsupported length: {value!r}; use numeric SVG user units')
    result = float(value.removesuffix('px'))
    if not math.isfinite(result):
        raise UnsupportedSVG('Non-finite coordinate')
    return result


def color(value):
    if value == 'none':
        return 'none'
    if 'url(' in value or value in ('currentColor', 'inherit'):
        raise UnsupportedSVG(f'Unsupported paint {value}')
    try:
        rgba = ImageColor.getcolor(value, 'RGBA')
    except ValueError as exc:
        raise UnsupportedSVG(f'Unsupported color {value}') from exc
    if rgba[3] != 255:
        raise UnsupportedSVG('Use fill-opacity/stroke-opacity for transparent colors')
    return '#%02X%02X%02X' % rgba[:3]


def multiply(a, b):
    aa, ab, ac, ad, ae, af = a
    ba, bb, bc, bd, be, bf = b
    return (aa*ba+ac*bb, ab*ba+ad*bb, aa*bc+ac*bd,
            ab*bc+ad*bd, aa*be+ac*bf+ae, ab*be+ad*bf+af)


def import_svg(source):
    raw = Path(source).read_text(encoding='utf-8-sig')
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise UnsupportedSVG('DTD/entity declarations are unsupported')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] != 'svg':
        raise UnsupportedSVG('Expected SVG root')
    vb = [float(v) for v in re.findall(NUMBER, root.get('viewBox', ''))]
    if vb and (len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0):
        raise UnsupportedSVG('Invalid viewBox')
    width = number(root.get('width'), vb[2] if vb else 0)
    height = number(root.get('height'), vb[3] if vb else 0)
    if width <= 0 or height <= 0:
        raise UnsupportedSVG('SVG requires positive width/height or viewBox')
    matrix = (1, 0, 0, 1, 0, 0)
    if vb:
        sx, sy = width / vb[2], height / vb[3]
        aspect = root.get('preserveAspectRatio', 'xMidYMid meet').strip()
        if aspect == 'none':
            matrix = (sx, 0, 0, sy, -vb[0]*sx, -vb[1]*sy)
        elif aspect in ('xMidYMid', 'xMidYMid meet'):
            scale = min(sx, sy)
            matrix = (scale, 0, 0, scale, (width-vb[2]*scale)/2-vb[0]*scale,
                      (height-vb[3]*scale)/2-vb[1]*scale)
        else:
            raise UnsupportedSVG(f'Unsupported preserveAspectRatio {aspect}')
    scene = {'version': 1, 'width': width, 'height': height, 'elements': []}

    def visit(node, inherited, transform, is_root=False):
        tag = node.tag.split('}')[-1]
        if tag in ('title', 'desc', 'metadata'):
            return
        if tag not in ('svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'polygon', 'polyline', 'line', 'text'):
            raise UnsupportedSVG(f'Unsupported SVG element <{tag}>')
        if tag == 'svg' and not is_root:
            raise UnsupportedSVG('Nested SVG viewports are unsupported')
        allowed = STYLE_KEYS | {'id', 'style', 'transform', 'width', 'height', 'viewBox',
            'preserveAspectRatio', 'version', 'd', 'x', 'y', 'rx', 'ry', 'cx', 'cy',
            'r', 'x1', 'x2', 'y1', 'y2', 'points'}
        for key in node.attrib:
            if key not in allowed:
                raise UnsupportedSVG(f'Unsupported attribute {key}')
        local = {}
        for declaration in node.get('style', '').split(';'):
            if declaration.strip():
                key, sep, value = declaration.partition(':')
                if not sep or key.strip() not in STYLE_KEYS:
                    raise UnsupportedSVG(f'Unsupported style {declaration}')
                local[key.strip()] = value.strip()
        for key in ('clip-path', 'mask', 'filter', 'class', 'vector-effect', 'stroke-dasharray',
                    'marker-start', 'marker-mid', 'marker-end', 'paint-order'):
            if key in node.attrib:
                raise UnsupportedSVG(f'Unsupported attribute {key}')
        style = dict(inherited)
        style.update({key: node.get(key) for key in STYLE_KEYS if key in node.attrib})
        style.update(local)
        if style.get('display') == 'none' or style.get('visibility') == 'hidden':
            return
        if 'transform' in node.attrib:
            m = Matrix(node.get('transform'))
            transform = multiply(transform, (m.a, m.b, m.c, m.d, m.e, m.f))
        a, b, c, d, e, f = transform
        def point(z):
            return {'x': a*z.real+c*z.imag+e, 'y': b*z.real+d*z.imag+f}
        if tag in ('g', 'svg'):
            if number(style.get('opacity'), 1) != 1:
                raise UnsupportedSVG('Group opacity requires compositing and is unsupported')
            for child in node:
                visit(child, style, transform)
            return
        opacity = number(style.get('opacity'), 1)
        fill_opacity = number(style.get('fill-opacity'), 1)
        stroke_opacity = number(style.get('stroke-opacity'), 1)
        if any(v < 0 or v > 1 for v in (opacity, fill_opacity, stroke_opacity)):
            raise UnsupportedSVG('Opacity must be between zero and one')
        fill = color(style.get('fill', 'black'))
        stroke = color(style.get('stroke', 'none'))
        sx, sy = math.hypot(a, b), math.hypot(c, d)
        if stroke != 'none' and (abs(sx-sy) > 1e-6 or abs(a*c+b*d) > 1e-6):
            raise UnsupportedSVG('Nonuniform/skewed stroke transform requires outline expansion')
        if stroke != 'none' and (style.get('stroke-linecap', 'butt') != 'butt' or
                                 style.get('stroke-linejoin', 'miter') != 'miter'):
            raise UnsupportedSVG('Only butt stroke caps and miter joins supported')
        # A stable generated identifier also avoids invalid/duplicate XML names.
        common = {'id': f'svg-{len(scene["elements"])+1}', 'fill': fill,
                  'stroke': stroke, 'strokeWidth': number(style.get('stroke-width'), 1)*sx,
                  'opacity': opacity, 'fillOpacity': fill_opacity, 'strokeOpacity': stroke_opacity}
        if tag == 'text':
            if len(node) or any(k in node.attrib for k in ('dx', 'dy', 'rotate', 'textLength', 'lengthAdjust')):
                raise UnsupportedSVG('Only plain single-line text is supported; no tspan/position lists')
            if b or c or a <= 0 or d <= 0 or abs(a-d) > 1e-6:
                raise UnsupportedSVG('Text supports translation and positive uniform scaling only')
            if style.get('text-anchor', 'start') != 'start' or stroke != 'none':
                raise UnsupportedSVG('Text requires start anchor and no stroke')
            if style.get('font-weight', 'normal') not in ('normal', '400', 'bold', '700') or style.get('font-style', 'normal') not in ('normal', 'italic'):
                raise UnsupportedSVG('Text supports normal/bold weight and normal/italic style')
            size = number(style.get('font-size'), 16)*a
            pos = point(complex(number(node.get('x')), number(node.get('y'))))
            text = node.text or ''
            if '\n' in text:
                raise UnsupportedSVG('Multiline SVG text needs explicit reconstruction')
            scene['elements'].append(dict(common, type='text', x=pos['x'], y=pos['y']-size*0.8,
                width=max(size, len(text)*size*0.7), height=size*1.25, text=text,
                fontSize=size, fontFamily=style.get('font-family', 'Arial'),
                bold=style.get('font-weight', 'normal') in ('bold', '700'),
                italic=style.get('font-style', 'normal') == 'italic'))
            return
        n = lambda key, default=0: number(node.get(key), default)
        if tag == 'path':
            path_data = node.get('d', '')
        elif tag == 'rect':
            x, y, w, h = n('x'), n('y'), n('width'), n('height')
            if w < 0 or h < 0:
                raise UnsupportedSVG('Negative rectangle size')
            rx = min(n('rx', n('ry')), w/2)
            ry = min(n('ry', rx), h/2)
            if rx < 0 or ry < 0:
                raise UnsupportedSVG('Negative corner radius')
            if rx and ry:
                path_data = f'M{x+rx},{y} H{x+w-rx} A{rx},{ry} 0 0 1 {x+w},{y+ry} V{y+h-ry} A{rx},{ry} 0 0 1 {x+w-rx},{y+h} H{x+rx} A{rx},{ry} 0 0 1 {x},{y+h-ry} V{y+ry} A{rx},{ry} 0 0 1 {x+rx},{y} Z'
            else:
                path_data = f'M{x},{y} h{w} v{h} h{-w} Z'
        elif tag in ('circle', 'ellipse'):
            x, y = n('cx'), n('cy')
            rx, ry = (n('r'), n('r')) if tag == 'circle' else (n('rx'), n('ry'))
            if rx <= 0 or ry <= 0:
                raise UnsupportedSVG('Ellipse radii must be positive')
            path_data = f'M{x-rx},{y} A{rx},{ry} 0 1 0 {x+rx},{y} A{rx},{ry} 0 1 0 {x-rx},{y} Z'
        elif tag == 'line':
            path_data = f'M{n("x1")},{n("y1")} L{n("x2")},{n("y2")}'
        else:
            coords = re.findall(NUMBER, node.get('points', ''))
            if len(coords) < 4 or len(coords) % 2:
                raise UnsupportedSVG('Invalid polygon/polyline points')
            path_data = 'M' + ','.join(coords[:2]) + ' L' + ' '.join(coords[2:]) + (' Z' if tag == 'polygon' else '')
        commands = []
        # Split only explicit moveto tokens, retaining the original close semantics.
        pieces = [piece for piece in re.split(r'(?=[Mm])', path_data) if piece.strip()]
        if style.get('fill-rule', 'nonzero') != 'nonzero' and len(pieces) > 1:
            raise UnsupportedSVG('Compound evenodd fill is unsupported')
        current = 0j
        for piece in pieces:
            if re.search(r'[zZ]\s*[^\s]', piece):
                raise UnsupportedSVG('Drawing after close requires a new moveto')
            path = parse_path(piece, current_pos=current)
            if not path:
                continue
            current = path[-1].end
            commands.append(dict(op='M', **point(path[0].start)))
            for segment in path:
                if isinstance(segment, Line):
                    commands.append(dict(op='L', **point(segment.end)))
                    continue
                if isinstance(segment, QuadraticBezier):
                    segment = CubicBezier(segment.start, segment.start+2/3*(segment.control-segment.start),
                                           segment.end+2/3*(segment.control-segment.end), segment.end)
                curves = segment.as_cubic_curves(max(1, math.ceil(abs(segment.delta)/45))) if isinstance(segment, Arc) else [segment]
                for curve in curves:
                    p1, p2 = point(curve.control1), point(curve.control2)
                    commands.append(dict(op='C', x1=p1['x'], y1=p1['y'], x2=p2['x'], y2=p2['y'], **point(curve.end)))
            if re.search(r'[zZ]\s*$', piece):
                commands.append({'op': 'Z'})
        if commands:
            scene['elements'].append(dict(common, type='path', commands=commands))

    visit(root, {}, matrix, True)
    return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    scene = import_svg(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(scene, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'output': str(args.output), 'elements': len(scene['elements'])}))


if __name__ == '__main__':
    main()
