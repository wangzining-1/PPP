"""Local PPP stages. Run --help; outputs never replace source files."""
import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
from PIL import Image, ImageChops

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from pixel_vectors import load_image


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def new_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(source, output, frame=None, ocr=True):
    """Normalize and cache OCR once; model reviews candidates against the image."""
    output = Path(output)
    key = {'source_sha256': file_hash(source), 'frame': frame, 'ocr': ocr,
           'pipeline_version': 1, 'pillow': importlib.metadata.version('Pillow'),
           'ocr_version': importlib.metadata.version('rapidocr-onnxruntime') if ocr else None}
    manifest_path = output / 'manifest.json'
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest.get('cache_key') == key and all((output / p).exists() for p in ['normalized.png', 'labels.json']):
            return {**manifest, 'cache_hit': True}
        raise ValueError('Existing output does not match source/options; choose another directory')
    image, metadata = load_image(source, frame)
    labels = []
    if ocr:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        white = Image.new('RGBA', image.size, 'white')
        white.alpha_composite(image)
        results, _ = engine(np.array(white.convert('RGB'))[:, :, ::-1])
        for index, (polygon, text, confidence) in enumerate(results or []):
            points = np.asarray(polygon)
            x, y = points.min(axis=0)
            right, bottom = points.max(axis=0)
            angle = math.degrees(math.atan2(points[1, 1]-points[0, 1], points[1, 0]-points[0, 0]))
            labels.append({'id': f'text-{index+1}', 'text': text, 'confidence': float(confidence),
                'box': [float(x), float(y), float(right-x), float(bottom-y)],
                'polygon': points.tolist(), 'angle_candidate': angle,
                'font_family': 'Arial', 'font_size': float(bottom-y)*0.8,
                'color': '#000000', 'review_needed': ['content', 'box', 'font', 'color', 'rotation', 'overlapping_graphics']})
    output = new_directory(output)
    image.save(output / 'normalized.png')
    write_json(output / 'labels.json', {'reviewed': False, 'labels': labels})
    manifest = {'cache_key': key, 'metadata': metadata, 'width': image.width, 'height': image.height,
        'ocr_labels': len(labels), 'status': 'OCR candidates require visual review',
        'cache_hit': False, 'output': str(output.resolve())}
    write_json(manifest_path, manifest)
    return manifest


def checked_labels(path):
    data = read_json(path)
    if data.get('reviewed') is not True:
        raise ValueError('labels.json must be visually reviewed; set reviewed=true only after actual inspection')
    if not isinstance(data.get('labels'), list):
        raise ValueError('labels must be an array')
    for label in data['labels']:
        if not isinstance(label.get('text'), str):
            raise ValueError('Each label requires exact text')
        box = label.get('box')
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(n, (float, int)) and math.isfinite(n) for n in box) or min(box[2:]) <= 0:
            raise ValueError('Each label requires finite positive [x,y,width,height]')
    return data['labels']


def erase(source, labels_path, output):
    """Provisional local text removal; always inspect crossing lines afterwards."""
    import cv2
    labels = checked_labels(labels_path)
    im = Image.open(source).convert('RGBA')
    if im.getchannel('A').getextrema() != (255, 255):
        raise ValueError('Local inpainting requires an explicitly composited opaque input; retain original alpha separately')
    rgb = np.array(im.convert('RGB'))
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    for label in labels:
        if label.get('erase', True) is False:
            continue
        x, y, w, h = label['box']
        # Explicit erasure polygon overrides rectangle for tight masks near arrows.
        polygon = label.get('erase_polygon', [[x, y], [x+w, y], [x+w, y+h], [x, y+h]])
        cv2.fillPoly(mask, [np.asarray(polygon, dtype=np.int32)], 255)
    repaired = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA) if np.any(mask) else rgb
    output = new_directory(output)
    Image.fromarray(mask).save(output / 'text-mask.png')
    Image.fromarray(repaired).save(output / 'graphics.png')
    report = {'status': 'provisional text removal; inspect every erased region and repair damaged graphics',
              'masked_pixels': int(np.count_nonzero(mask)), 'source_sha256': file_hash(source)}
    write_json(output / 'erase-report.json', report)
    return report


def trace(source, output, precision=8, max_paths=20000):
    import vtracer
    from svg_to_scene import import_svg
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a new output directory')
    with Image.open(source) as image:
        if image.convert('RGBA').getchannel('A').getextrema() != (255, 255):
            raise ValueError('VTracer does not preserve alpha; explicitly composite or reconstruct transparent shapes')
        if image.width * image.height > 16_000_000:
            raise ValueError('More than 16 million pixels: split into reviewed regions before tracing')
    output.mkdir(parents=True)
    svg = output / 'graphics.svg'
    vtracer.convert_image_to_svg_py(str(source), str(svg), colormode='color',
        hierarchical='stacked', mode='spline', filter_speckle=0,
        color_precision=precision, layer_difference=16, corner_threshold=60,
        length_threshold=4.0, max_iterations=10, splice_threshold=45, path_precision=3)
    scene = import_svg(svg)
    if len(scene['elements']) > max_paths:
        raise ValueError(f'Traced {len(scene["elements"])} paths, above budget {max_paths}; SVG retained for inspection')
    write_json(output / 'graphics.scene.json', scene)
    report = {'source_sha256': file_hash(source), 'vtracer': importlib.metadata.version('vtracer'),
        'paths': len(scene['elements']), 'color_precision': precision,
        'status': 'approximate spline tracing; geometry and semantics need review'}
    write_json(output / 'trace-report.json', report)
    return report


def merge_labels(scene_path, labels_path, output):
    labels = checked_labels(labels_path)
    scene = read_json(scene_path)
    if Path(output).exists():
        raise ValueError('Output exists; choose a new scene path')
    ids = {el['id'] for el in scene['elements']}
    for index, label in enumerate(labels):
        identifier = label.get('id', f'text-{index+1}')
        if identifier in ids:
            raise ValueError(f'Duplicate scene ID: {identifier}')
        ids.add(identifier)
        x, y, width, height = label['box']
        element = {'id': identifier, 'type': 'text', 'text': label['text'],
            'x': x, 'y': y, 'width': width, 'height': height,
            'fontSize': label.get('font_size', height*0.8),
            'fontFamily': label.get('font_family', 'Arial'), 'fill': label.get('color', '#000000'),
            'bold': label.get('bold', False), 'italic': label.get('italic', False),
            'align': label.get('align', 'left')}
        if label.get('rotation', 0):
            # Compiler's current text subset is horizontal; don't silently flatten.
            raise ValueError(f'{identifier}: rotated text requires an explicit supported scene reconstruction')
        scene['elements'].append(element)
    write_json(output, scene)
    return scene


def compare(source, rendered, output, background='white', threshold=0):
    if not 0 <= threshold <= 255:
        raise ValueError('threshold must be 0..255')
    def composite(path):
        im = Image.open(path).convert('RGBA')
        base = Image.new('RGBA', im.size, background)
        base.alpha_composite(im)
        return base.convert('RGB')
    reference, candidate = composite(source), composite(rendered)
    if reference.size != candidate.size:
        raise ValueError(f'Image sizes differ: {reference.size} vs {candidate.size}; render at source size explicitly')
    error = np.abs(np.asarray(reference).astype(np.int16)-np.asarray(candidate).astype(np.int16))
    changed = np.max(error, axis=2) > threshold
    tiles = []
    for y in range(0, reference.height, 128):
        for x in range(0, reference.width, 128):
            tile = error[y:y+128, x:x+128]
            if tile.max() > threshold:
                tiles.append({'box': [x, y, min(128, reference.width-x), min(128, reference.height-y)],
                              'mean_error': float(tile.mean()), 'max_error': int(tile.max())})
    report = {'rgb_mae': float(error.mean()), 'rgb_max_error': int(error.max()),
        'changed_pixel_fraction': float(changed.mean()), 'threshold': threshold,
        'background': background, 'width': reference.width, 'height': reference.height,
        'worst_tiles': sorted(tiles, key=lambda t: t['mean_error'], reverse=True)[:8],
        'pixel_identical_under_stated_conditions': bool(error.max() == 0),
        'semantic_correctness': 'requires review of entities, connections, arrow direction and labels'}
    output = new_directory(output)
    Image.blend(reference, candidate, 0.5).save(output / 'overlay.png')
    ImageChops.difference(reference, candidate).save(output / 'difference.png')
    Image.fromarray((changed * 255).astype(np.uint8)).save(output / 'changed-mask.png')
    for index, tile in enumerate(report['worst_tiles']):
        x, y, w, h = tile['box']
        reference.crop((x, y, x+w, y+h)).save(output / f'roi-{index+1}-reference.png')
        candidate.crop((x, y, x+w, y+h)).save(output / f'roi-{index+1}-rendered.png')
    write_json(output / 'comparison.json', report)
    return report


def audit(pptx, scene_path=None):
    ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with zipfile.ZipFile(pptx) as archive:
        slide_names = sorted(n for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml'))
        slides = [ET.fromstring(archive.read(n)) for n in slide_names]
        names = [e.get('name') for slide in slides for e in slide.findall('.//p:cNvPr', ns)]
        texts = [''.join(e.itertext()) for slide in slides for e in slide.findall('.//a:t', ns)]
        pictures = sum(len(s.findall('.//p:pic', ns)) for s in slides)
        blips = sum(len(s.findall('.//a:blip', ns)) for s in slides)
        media = [n for n in archive.namelist() if n.startswith('ppt/media/')]
        external = []
        for n in archive.namelist():
            if n.endswith('.rels'):
                external.extend(e.get('Target') for e in ET.fromstring(archive.read(n)) if e.get('TargetMode') == 'External')
        result = {'slides': len(slides), 'shapes': sum(len(s.findall('.//p:sp', ns)) for s in slides),
                  'native_text_runs': len(texts), 'text': texts, 'pictures': pictures,
                  'image_fills': blips, 'media_files': media, 'external_relationships': external,
                  'native_vector_only': pictures == 0 and blips == 0 and not media and not external,
                  'powerpoint_application_verified': False}
        if scene_path:
            scene = read_json(scene_path)
            result['missing_ids'] = [el['id'] for el in scene['elements'] if el['id'] not in names]
            shape_map = {}
            for slide in slides:
                for shape in slide.findall('.//p:sp', ns):
                    name_node = shape.find('p:nvSpPr/p:cNvPr', ns)
                    if name_node is not None:
                        shape_map.setdefault(name_node.get('name'), []).append(shape)
            result['object_errors'] = []
            for el in scene['elements']:
                matches = shape_map.get(el['id'], [])
                if len(matches) != 1:
                    result['object_errors'].append({'id': el['id'], 'error': 'missing or duplicate native shape'})
                    continue
                shape = matches[0]
                if el['type'] == 'text':
                    paragraphs = shape.findall('p:txBody/a:p', ns)
                    actual = '\n'.join(''.join(n.text or '' for n in p.iter() if n.tag == '{'+ns['a']+'}t') for p in paragraphs)
                    if not paragraphs or actual != el['text']:
                        result['object_errors'].append({'id': el['id'], 'expected': el['text'], 'actual': actual})
                elif el['type'] in ('path', 'line'):
                    if shape.find('p:spPr/a:custGeom', ns) is None:
                        result['object_errors'].append({'id': el['id'], 'error': 'expected native custom geometry'})
                elif el['type'] in ('rect', 'ellipse'):
                    geometry = shape.find('p:spPr/a:prstGeom', ns)
                    if geometry is None or geometry.get('prst') != el['type']:
                        result['object_errors'].append({'id': el['id'], 'error': 'preset geometry differs'})
            result['scene_contract_pass'] = not result['missing_ids'] and not result['object_errors'] and result['native_vector_only'] and result['shapes'] == len(scene['elements'])
    return result


def doctor():
    packages = ['Pillow', 'PyYAML', 'vtracer', 'svgelements', 'svgpathtools', 'numpy',
                'opencv-python', 'rapidocr-onnxruntime', 'onnxruntime', 'resvg-py']
    found = {}
    for package in packages:
        try:
            found[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            found[package] = None
    return {'python': sys.executable, 'packages': found, 'ready': all(found.values()),
            'scope': 'local image/OCR/SVG tools; Node/PPTX compiler verified separately'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    p = commands.add_parser('prepare')
    p.add_argument('source', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--frame', type=int); p.add_argument('--no-ocr', action='store_true')
    for name in ['erase', 'merge']:
        p = commands.add_parser(name)
        p.add_argument('source', type=Path); p.add_argument('labels', type=Path); p.add_argument('output', type=Path)
    p = commands.add_parser('trace')
    p.add_argument('source', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--color-precision', type=int, choices=range(1, 9), default=8)
    p.add_argument('--max-paths', type=int, default=20000)
    p = commands.add_parser('compare')
    p.add_argument('source', type=Path); p.add_argument('rendered', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--background', default='white'); p.add_argument('--threshold', type=int, default=0)
    p = commands.add_parser('audit')
    p.add_argument('pptx', type=Path); p.add_argument('--scene', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'doctor': result = doctor()
        elif args.command == 'prepare': result = prepare(args.source, args.output, args.frame, not args.no_ocr)
        elif args.command == 'erase': result = erase(args.source, args.labels, args.output)
        elif args.command == 'trace': result = trace(args.source, args.output, args.color_precision, args.max_paths)
        elif args.command == 'merge':
            scene = merge_labels(args.source, args.labels, args.output)
            result = {'elements': len(scene['elements']), 'output': str(args.output)}
        elif args.command == 'compare': result = compare(args.source, args.rendered, args.output, args.background, args.threshold)
        elif args.command == 'audit': result = audit(args.pptx, args.scene)
    except (ValueError, OSError) as error:
        parser.exit(2, f'{error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'doctor' and not result['ready']:
        sys.exit(1)
    if args.command == 'audit' and not result.get('scene_contract_pass', result['native_vector_only']):
        sys.exit(1)


if __name__ == '__main__':
    main()
