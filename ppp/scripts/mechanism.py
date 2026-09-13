"""Reviewed mechanism graph -> ordered native scene and built-in image prompt.

Standard library only. Recognition is performed by the host vision model;
this module validates, orders and compiles its explicit structured result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

VERSION = 4
KINDS = {'activation', 'inhibition', 'transport', 'binding', 'association', 'unknown'}
CAUSAL = {'activation', 'inhibition', 'transport'}
STATUSES = {'supported', 'hypothesis', 'uncertain'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def validate(data):
    if data.get('version') != 1 or data.get('reviewed') is not True:
        raise ValueError('Expected version=1 and reviewed=true after inspecting context/image')
    nodes, edges = data.get('nodes'), data.get('edges')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 200 or not isinstance(edges, list) or len(edges) > 500:
        raise ValueError('Expected 1..200 nodes and 0..500 edges; split larger diagrams')
    for items in (nodes, edges):
        ids = set()
        for item in items:
            identifier = item.get('id')
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', identifier) or identifier in ids:
                raise ValueError('IDs must be unique ASCII XML-safe names within nodes/edges')
            ids.add(identifier)
    ids = {n['id'] for n in nodes}
    for node in nodes:
        if not isinstance(node.get('label'), str) or not node['label'].strip() or len(node['label']) > 160:
            raise ValueError('Node label must contain 1..160 characters')
    for edge in edges:
        if edge.get('source') not in ids or edge.get('target') not in ids:
            raise ValueError('Edge endpoint is missing')
        if edge.get('kind') not in KINDS or edge.get('status') not in STATUSES:
            raise ValueError('Unsupported relation kind/status')
        if not isinstance(edge.get('evidence'), str) or not edge['evidence'].strip():
            raise ValueError('Every edge requires evidence: context span, image ROI or citation')
        if edge['kind'] == 'unknown' and edge['status'] != 'uncertain':
            raise ValueError('Unknown relations must be uncertain')


def causal_order(nodes, edges):
    """Collapse strongly connected components, then layer their acyclic graph."""
    ids = sorted(n['id'] for n in nodes)
    adjacency = {n: set() for n in ids}
    for edge in edges:
        if edge['kind'] in CAUSAL and edge['status'] == 'supported':
            adjacency[edge['source']].add(edge['target'])
    # Bounded at 200 nodes; iterative reachability avoids recursion limits.
    reachable = {}
    for node in ids:
        seen, stack = set(), [node]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current); stack.extend(adjacency[current] - seen)
        reachable[node] = seen
    components, pending = [], set(ids)
    while pending:
        first = min(pending)
        component = sorted(n for n in pending if n in reachable[first] and first in reachable[n])
        components.append(component); pending.difference_update(component)
    owner = {n: i for i, component in enumerate(components) for n in component}
    parents = {i: set() for i in range(len(components))}
    for source in ids:
        for target in adjacency[source]:
            if owner[source] != owner[target]: parents[owner[target]].add(owner[source])
    levels, pending = {}, set(parents)
    while pending:
        ready = sorted(i for i in pending if parents[i] <= levels.keys())
        for i in ready:
            levels[i] = max((levels[p] + 1 for p in parents[i]), default=0)
        pending.difference_update(ready)
    layers = {n: levels[owner[n]] for n in ids}
    cycles = [c for c in components if len(c) > 1 or c[0] in adjacency[c[0]]]
    return layers, cycles


def wrap_label(text):
    # Conservative display-width approximation; PPT fonts still need visual review.
    lines, line, width = [], '', 0
    for char in text:
        units = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1.7 if char in 'MWmw@' else 1
        if char == '\n':
            lines.append(line); line, width = '', 0
            continue
        if line and width + units > 17:
            lines.append(line); line, width = '', 0
        line += char; width += units
    lines.append(line)
    return '\n'.join(lines)


def compile_graph(data, max_shapes=1000):
    validate(data)
    if type(max_shapes) is not int or not 1 <= max_shapes <= 1000:
        raise ValueError('max_shapes must be 1..1000')
    nodes = sorted(data['nodes'], key=lambda n: n['id'])
    edges = sorted(data['edges'], key=lambda e: e['id'])
    layers, cycles = causal_order(nodes, edges)
    node_order = sorted(layers, key=lambda n: (layers[n], n))
    edge_order = sorted(edges, key=lambda e: (max(layers[e['source']], layers[e['target']]), e['id']))
    # Allocate an exterior lane per non-forward edge. No edge is deleted to break a cycle.
    routed = [e for e in edge_order if layers[e['source']] >= layers[e['target']]]
    top = 60
    labels = {n['id']: wrap_label(n['label']) for n in nodes}
    box_height = max(64, max(24 * len(label.splitlines()) + 24 for label in labels.values()))
    row_step = box_height + 60
    positions, rows = {}, {}
    for node in node_order:
        layer = layers[node]; row = rows.get(layer, 0); rows[layer] = row + 1
        positions[node] = (60 + layer * 320, top + row * row_step)
    width = max(640, 160 + (max(layers.values()) + 1) * 320 + 24 * len(routed))
    height = top + max(rows.values()) * row_step + 90
    elements = []
    def line(identifier, x1, y1, x2, y2, color, **extra):
        return dict(id=identifier, type='line', x1=x1, y1=y1, x2=x2, y2=y2, stroke=color, strokeWidth=2, **extra)
    for edge in edge_order:
        source, target = edge['source'], edge['target']
        sx, sy = positions[source]; tx, ty = positions[target]
        uncertain = edge['status'] == 'uncertain'
        color = '#7C8490' if uncertain else '#B36B00' if edge['status'] == 'hypothesis' else '#35465C'
        causal = edge['kind'] in CAUSAL and not uncertain
        routed_edge = layers[source] >= layers[target]
        meta = {'relation_id': edge['id'], 'kind': edge['kind'], 'status': edge['status'], 'evidence': edge['evidence']}
        if routed_edge:
            lane_index = routed.index(edge)
            lane = max(x for x, y in positions.values()) + 240 + 24 * lane_index
            x1, y1, x2, y2 = sx + 200, sy + box_height / 2 - 12, tx + 224, ty + box_height / 2 + 12
            elements.append(dict(id='route.' + edge['id'], type='path', fill='none', stroke=color, strokeWidth=2,
                commands=[dict(op='M', x=x1, y=y1), dict(op='L', x=lane, y=y1),
                          dict(op='L', x=lane, y=y2), dict(op='L', x=x2, y=y2)], metadata=meta))
            x1, y1 = x2, y2
            x2 = tx + 210
        else:
            x1, y1, x2, y2 = sx + 200, sy + box_height / 2, tx - 10, ty + box_height / 2
        main = line('edge.' + edge['id'], x1, y1, x2, y2, color, metadata=meta)
        if causal and edge['kind'] != 'inhibition': main['arrowEnd'] = 'triangle'
        elements.append(main)
        if causal and edge['kind'] == 'inhibition':
            # End cap perpendicular to final segment, snapped to the 0.5 px grid.
            dx, dy = x2 - x1, y2 - y1
            length = (dx * dx + dy * dy) ** 0.5 or 1
            px, py = round(-dy / length * 8 * 2) / 2, round(dx / length * 8 * 2) / 2
            elements.append(line('bar.' + edge['id'], x2-px, y2-py, x2+px, y2+py, color, metadata=meta))
        if edge['status'] != 'supported' or edge['kind'] in {'binding', 'association'}:
            label = '?' if uncertain else 'hypothesis' if edge['status'] == 'hypothesis' else edge['kind']
            lx = lane + 4 if routed_edge else (x1 + x2) / 2 - 45
            ly = ty + box_height / 2 + 12 if routed_edge else (y1 + y2) / 2 - 24
            elements.append(dict(id='note.' + edge['id'], type='text', x=round(lx*2)/2, y=round(ly*2)/2,
                                 width=100, height=22, text=label, fontSize=14, fill=color))
    for node in node_order:
        x, y = positions[node]
        elements.append(dict(id='node.' + node, type='rect', x=x, y=y, width=200, height=box_height,
                             fill='#E8F1F5', stroke='#476679', strokeWidth=2, metadata={'entity_id': node}))
        elements.append(dict(id='label.' + node, type='text', x=x+8, y=y+12, width=184, height=box_height-16,
                             text=labels[node], fontSize=18, fill='#1D3443', align='center'))
    elements.append(dict(id='legend', type='text', x=60, y=height-72, width=width-100, height=60,
        text='Arrow: activation/transport   Bar: inhibition\n?: uncertain   Amber: hypothesis', fontSize=14, fill='#35465C'))
    shapes = sum(e['type'] != 'text' for e in elements)
    if shapes > max_shapes: raise ValueError(f'{shapes} native graphics exceed budget {max_shapes}')
    plan = dict(layers=layers, cycles=cycles, node_order=node_order, edge_order=[e['id'] for e in edge_order],
                uncertain_edges=[e['id'] for e in edges if e['status'] == 'uncertain'],
                shapes=shapes, text_objects=len(elements)-shapes, status='candidate; semantic and visual review required')
    scene = dict(version=1, width=width, height=height, background='none', elements=elements,
                 metadata={'compiler': VERSION, 'plan': plan})
    prompt = ('Create a clean scientific mechanism composition reference, flat colors, white background, '
              'separate silhouettes and generous spacing. This is a raster reference, not final vector artwork. '
              'Use ONLY the entities and relations in the JSON below. Keep inhibition bars and feedback loops. '
              'Show uncertain relations with ? and no causal arrow; mark hypotheses explicitly. '
              'Do not invent biology or use this generated image as scientific evidence. '
              'Follow layer order; nodes in a cycle have no strict internal temporal order.\n' +
              canonical({'nodes': nodes, 'edges': edges, 'layers': layers, 'cycles': cycles}))
    return {'plan': plan, 'scene': scene, 'image_prompt': prompt}


def build(data, root, max_shapes=1000):
    # Cache depends on every input field, options and compiler version. Verify bytes before reuse.
    key = digest(canonical({'graph': data, 'max_shapes': max_shapes, 'compiler': VERSION}))
    folder = Path(root) / key
    manifest = folder / 'manifest.json'
    if manifest.exists():
        try:
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            files = saved.get('files') if isinstance(saved, dict) else None
            if (isinstance(files, dict) and set(files) == {'scene.json', 'plan.json', 'image-prompt.txt'}
                    and saved.get('key') == key and all(digest((folder / name).read_text(encoding='utf-8')) == checksum
                    for name, checksum in files.items())):
                return dict(key=key, cache_hit=True, scene=str(folder / 'scene.json'), plan=str(folder / 'plan.json'),
                            image_prompt=str(folder / 'image-prompt.txt'))
        except (OSError, ValueError, KeyError, TypeError): pass
    result = compile_graph(data, max_shapes)
    folder.mkdir(parents=True, exist_ok=True)
    contents = {'scene.json': canonical(result['scene']), 'plan.json': canonical(result['plan']),
                'image-prompt.txt': result['image_prompt']}
    for name, content in contents.items(): (folder / name).write_text(content, encoding='utf-8')
    manifest.write_text(canonical({'key': key, 'files': {name: digest(value) for name, value in contents.items()}}), encoding='utf-8')
    return dict(key=key, cache_hit=False, scene=str(folder / 'scene.json'), plan=str(folder / 'plan.json'),
                image_prompt=str(folder / 'image-prompt.txt'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('graph', type=Path)
    parser.add_argument('output', type=Path, help='Cache root; results are keyed by content hash')
    parser.add_argument('--max-shapes', type=int, default=1000)
    args = parser.parse_args()
    try:
        print(canonical(build(json.loads(args.graph.read_text(encoding='utf-8-sig')), args.output, args.max_shapes)))
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__': main()
