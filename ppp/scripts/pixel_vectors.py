"""Lossless visible 8-bit RGBA cells to merged vector rectangles."""
import argparse
import io
import json
from pathlib import Path
from PIL import Image, ImageCms, ImageOps


def load_image(path, frame):
    with Image.open(path) as source:
        count = getattr(source, 'n_frames', 1)
        if count > 1 and frame is None:
            raise ValueError(f'{count} frames found; specify --frame (zero-based)')
        index = 0 if frame is None else frame
        if not 0 <= index < count:
            raise ValueError(f'frame must be between 0 and {count - 1}')
        source.seek(index)
        mode = source.mode
        if mode in ('I', 'F') or mode.startswith('I;16'):
            raise ValueError('High-bit-depth input needs an explicit 8-bit conversion first')
        profile = source.info.get('icc_profile')
        if mode == 'CMYK' and not profile:
            raise ValueError('CMYK without ICC needs explicit color conversion first')
        oriented = ImageOps.exif_transpose(source)
        rgba = oriented.convert('RGBA')
        color_note = 'unprofiled input interpreted as sRGB'
        if profile:
            base = oriented if mode in ('CMYK', 'LAB', 'RGB', 'L') else oriented.convert('RGB')
            rgb = ImageCms.profileToProfile(base, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                ImageCms.createProfile('sRGB'), outputMode='RGB')
            rgb.putalpha(rgba.getchannel('A'))
            rgba = rgb
            color_note = 'embedded ICC converted to sRGB'
        return rgba, {'source_format': source.format, 'source_mode': mode,
            'frame': index, 'frames': count, 'color_conversion': color_note,
            'normalization': 'EXIF orientation applied; 8-bit RGBA; invisible RGB omitted'}


def rectangles(im, max_shapes):
    if max_shapes < 1:
        raise ValueError('shape budget must be positive')
    pixels = im.load()
    result, active = [], {}
    for y in range(im.height):
        following = {}
        x = 0
        while x < im.width:
            color = pixels[x, y]
            end = x + 1
            while end < im.width and pixels[end, y] == color:
                end += 1
            if color[3]:
                key = (x, end - x, color)
                if key in active:
                    rect = active[key]
                    rect[3] += 1
                else:
                    rect = [x, y, end - x, 1, color]
                    result.append(rect)
                    if len(result) > max_shapes:
                        raise ValueError(f'shape budget exceeded: more than {max_shapes}; no quantization performed')
                following[key] = rect
            x = end
        active = following
    return result


def svg_text(width, height, rects):
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    for x, y, w, h, (r, g, b, a) in rects:
        lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#{r:02x}{g:02x}{b:02x}" fill-opacity="{a/255:.10f}"/>')
    return '\n'.join(lines + ['</svg>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path)
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--frame', type=int)
    parser.add_argument('--max-shapes', type=int, default=20000)
    parser.add_argument('--formats', action='store_true')
    args = parser.parse_args()
    if args.formats:
        Image.init()
        print(json.dumps({k: v for k, v in Image.registered_extensions().items() if v in Image.OPEN}, indent=2))
        return
    if args.input is None or args.out_dir is None:
        parser.error('input and --out-dir are required')
    if args.out_dir.exists():
        parser.error('output directory already exists; choose a new directory')
    try:
        im, meta = load_image(args.input, args.frame)
        rects = rectangles(im, args.max_shapes)
    except (ValueError, OSError) as error:
        parser.exit(2, f'{error}\n')
    data = {'schema': 'ppp.rectangles.v1', 'width': im.width, 'height': im.height,
        'shape_count': len(rects), 'metadata': meta, 'rectangles': rects}
    args.out_dir.mkdir(parents=True)
    (args.out_dir / 'geometry.json').write_text(json.dumps(data), encoding='utf-8')
    (args.out_dir / 'vector.svg').write_text(svg_text(im.width, im.height, rects), encoding='utf-8')
    print(json.dumps({'width': im.width, 'height': im.height, 'shapes': len(rects), 'out_dir': str(args.out_dir)}))


if __name__ == '__main__':
    main()
