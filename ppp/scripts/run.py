"""Portable PPP entry point. Runtime paths come from runtime.local.json.

Configure python, node, node_modules and presentation_skill using actual
host paths. mechanism requires only the invoking Python standard library.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    scripts = Path(__file__).resolve().parent
    args = sys.argv[1:]
    if not args or args[0] in ('help', '--help', '-h'):
        print('PPP: mechanism | doctor | prepare | erase | budget | render | trace | merge | export | finalize | svg | compare | audit')
        return 0
    if args[0] == 'mechanism':
        return subprocess.call([sys.executable, str(scripts / 'mechanism.py'), *args[1:]])
    config_path = scripts.parent / 'runtime.local.json'
    if not config_path.exists():
        raise ValueError('Configure runtime.local.json with actual host paths; see references/portable-runtime.md')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    for key in ('python', 'node', 'node_modules'):
        if not Path(config[key]).is_absolute() or not Path(config[key]).exists():
            raise ValueError(f'Invalid runtime path: {key}')
    env = dict(os.environ, RUNTIME_NODE_MODULES=config['node_modules'], PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    node_scripts = {'export': 'scene_to_pptx.mjs', 'render': 'render_pptx.mjs', 'finalize': 'finalize_pptx.mjs'}
    python_scripts = {'budget': 'budget_vectorize.py', 'svg': 'svg_to_scene.py'}
    command = args[0]
    if command in node_scripts:
        if command == 'finalize' and len(args) >= 4:
            code = subprocess.call([config['python'], str(scripts / 'budget_vectorize.py'), 'audit', args[2]], env=env)
            if code: return code
        return subprocess.call([config['node'], str(scripts / node_scripts[command]), *args[1:]], env=env)
    if command in python_scripts:
        return subprocess.call([config['python'], str(scripts / python_scripts[command]), *args[1:]], env=env)
    code = subprocess.call([config['python'], str(scripts / 'ppp.py'), *args], env=env)
    if command == 'doctor' and not code:
        code = subprocess.call([config['node'], str(scripts / 'check_node.mjs')], env=env)
    return code


if __name__ == '__main__':
    try: sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr); sys.exit(2)
