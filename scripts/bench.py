#!/usr/bin/env python3
"""Prepare, run, and collect a pinned drawing-only CAD Bench experiment."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tomllib
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'configs/experiment.json'
MANIFEST = ROOT / 'configs/cohort.lock.json'
HARBOR = ROOT / '.venv/bin/harbor'


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_env():
    """Simple KEY=value file; no shell execution, expansion, or secret logging."""
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                key, sep, value = line.partition('=')
                if not sep or not key.replace('_', '').isalnum():
                    raise ValueError('Invalid .env assignment')
                if value:
                    os.environ.setdefault(key, value.strip().strip('\"\''))


def check_version():
    from importlib.metadata import version
    actual = version('harbor')
    expected = read(CONFIG)['harbor_version']
    if actual != expected:
        raise RuntimeError(f'Harbor {actual}; expected {expected}')


async def dataset_metadata(config):
    from harbor.registry.client.package import PackageDatasetClient
    client = PackageDatasetClient()
    metadata = await client._get_dataset_metadata(
        config['dataset'] + '@' + config['dataset_digest'])
    if metadata.version != config['dataset_digest']:
        raise RuntimeError('Registry dataset digest differs from experiment')
    return metadata.model_dump(mode='json')


def drawing_task(path):
    instruction = (path / 'instruction.md').read_text()
    task = tomllib.loads((path / 'task.toml').read_text())
    images = sorted((path / 'environment').glob('*.png'))
    image_only = 'drawing is your only source of geometry' in instruction
    if not image_only:
        return None
    if len(images) != 1 or task['verifier'].get('environment_mode') != 'separate':
        raise RuntimeError(f'{path.name}: unexpected drawing/verifier contract')
    name = task['task']['name'].split('/')[-1]
    if name != path.name:
        raise RuntimeError('Task directory/name mismatch')
    return {'name': name, 'path': str(path.relative_to(ROOT)),
            'drawing': str(images[0].relative_to(ROOT)),
            'drawing_sha256': sha(images[0]),
            'files': {str(p.relative_to(path)): sha(p)
                      for p in sorted(path.rglob('*')) if p.is_file()},
            'reference': str((path/'tests/grader/reference.FCStd').relative_to(ROOT))}


def prepare(args):
    check_version()
    config = read(CONFIG)
    if args.download:
        subprocess.run([str(HARBOR), 'datasets', 'download',
                        config['dataset']+'@'+config['dataset_digest'],
                        '-o', str(ROOT/'data')], check=True, cwd=ROOT)
    metadata = asyncio.run(dataset_metadata(config))
    refs = {t['name']: t['ref'] for t in metadata['task_ids']}
    tasks = []
    for path in sorted((ROOT/'data/cad-bench').glob('*/task.toml')):
        entry = drawing_task(path.parent)
        if entry:
            if entry['name'] not in refs:
                raise RuntimeError('Local task is outside pinned dataset')
            entry['package_digest'] = refs[entry['name']]
            tasks.append(entry)
    if len(tasks) != 40:
        raise RuntimeError(f'Expected 40 drawing-only tasks, found {len(tasks)}')
    count = args.count or config['pilot_count']
    if not len(config['anchor_tasks']) <= count <= 40:
        raise ValueError('Cohort count must be between anchor count and 40')
    anchors = config['anchor_tasks']
    remaining = [t['name'] for t in tasks if t['name'] not in anchors]
    random.Random(config['cohort_seed']).shuffle(remaining)
    selected = anchors + remaining[:count-len(anchors)]
    manifest = {'schema_version': 1, 'dataset': config['dataset'],
                'dataset_digest': config['dataset_digest'],
                'seed': config['cohort_seed'], 'selection':
                'Two named anchors, then seeded sample without replacement; selected before model results.',
                'pilot': selected, 'image_tasks': tasks}
    if MANIFEST.exists() and read(MANIFEST) != manifest:
        if not args.replace_cohort:
            raise RuntimeError('Cohort already frozen. Use --replace-cohort for a NEW experiment.')
    write(MANIFEST, manifest)
    write(ROOT/'data/dataset-metadata.json', metadata)
    print(f'Frozen {count}-task pilot from {len(tasks)} drawing-only tasks:')
    print('\n'.join(selected))


def verify_task(entry):
    base = ROOT / entry['path']
    actual = {str(p.relative_to(base)): sha(p)
              for p in sorted(base.rglob('*')) if p.is_file()}
    if actual != entry['files']:
        raise RuntimeError(f"Task files changed after freeze: {entry['name']}")
    drawing_task(base)


def selected_cells(args):
    c = read(CONFIG)
    cells = list(c['cells'])
    exclusion=ROOT/'configs/exclusions.json'
    excluded=set(read(exclusion)['cells']) if exclusion.exists() else set()
    cells=[cell for cell in cells if cell['id'] not in excluded]
    if args.cell:
        cells = [cell for cell in cells if cell['id'] in args.cell]
        missing = set(args.cell)-{cell['id'] for cell in cells}
        if missing:
            raise ValueError(f'Unknown cells: {sorted(missing)}')
    for cell in cells:
        if not cell.get('version'):
            raise ValueError(f"Pin harness version for {cell['id']} before running")
    return cells


def claude_token():
    """Use an explicit token or an unexpired native CLI credential in memory."""
    explicit=os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
    if explicit:
        return explicit
    path=Path.home()/'.claude/.credentials.json'
    if path.is_file():
        credential=read(path).get('claudeAiOauth',{})
        if credential.get('expiresAt',0)>time.time()*1000+30000:
            return credential.get('accessToken')
    return None


def enhanced_task(entry, enhancement):
    """Make an auditable derived agent image; never change verifier files."""
    source = ROOT/entry['path']
    adapter_paths=[ROOT/'tools'/n for n in ('start-freecad-mcp.sh','start-freecad-mcp.FCMacro','run-freecad-mcp.py','mcp-requirements.lock')]
    adapter_hash=hashlib.sha256(''.join(sha(p) for p in adapter_paths).encode()).hexdigest()
    out = ROOT/'data/variants'/enhancement['id']/adapter_hash[:12]/entry['name']
    if enhancement['kind'] != 'tool':
        return source
    tool = ROOT/enhancement['path']
    if not (tool/'pyproject.toml').exists():
        raise RuntimeError('Missing frozen FreeCAD MCP source; run setup-tools.py')
    if not (ROOT/'configs/enhancements.lock.json').exists():
        raise RuntimeError('Freeze enhancement hashes with setup-tools.py first')
    if not out.exists():
        shutil.copytree(source, out)
        env = out/'environment'
        shutil.copytree(tool, env/'cad-bench-tools/freecad-mcp',
                        ignore=shutil.ignore_patterns('.git','__pycache__','.venv'))
        for name in ('start-freecad-mcp.sh','start-freecad-mcp.FCMacro','run-freecad-mcp.py'):
            shutil.copyfile(ROOT/'tools'/name, env/'cad-bench-tools'/name)
        shutil.copyfile(ROOT/'tools/mcp-requirements.lock', env/'cad-bench-tools/mcp-requirements.lock')
        addition = '''
# Experimental arm: frozen FreeCAD MCP, local to this isolated agent container.
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth libgl1 libxrender1 libxext6 libsm6 libice6 && apt-get clean
COPY cad-bench-tools/ /opt/cad-bench-tools/
RUN python3 -m venv /opt/cad-bench-mcp && /opt/cad-bench-mcp/bin/pip install --no-cache-dir -r /opt/cad-bench-tools/mcp-requirements.lock && /opt/cad-bench-mcp/bin/pip install --no-deps --no-build-isolation /opt/cad-bench-tools/freecad-mcp && chmod +x /opt/cad-bench-tools/start-freecad-mcp.sh
'''
        with (env/'Dockerfile').open('a') as f:
            f.write(addition)
        write(out/'variant-provenance.json', {'base_task_digest': entry['package_digest'],
                                            'enhancement': enhancement,
                                            'adapter_sha256': adapter_hash,
                                            'agent_dockerfile_sha256': sha(env/'Dockerfile')})
    for p in (source/'tests').rglob('*'):
        if p.is_file() and sha(p) != sha(out/'tests'/p.relative_to(source/'tests')):
            raise RuntimeError('Derived verifier differs from frozen official verifier')
    if sha(source/'instruction.md') != sha(out/'instruction.md'):
        raise RuntimeError('Derived task changed drawing instruction')
    return out


def verify_enhancements(requested):
    if not requested:
        return
    locked=read(ROOT/'configs/enhancements.lock.json')
    selected=[e for e in locked['enhancements'] if e['id'] in requested]
    if len(selected) != len(set(requested)):
        raise RuntimeError('Selected enhancement is not frozen')
    for item in selected:
        path=ROOT/item['path']
        actual={str(p.relative_to(path)):sha(p) for p in sorted(path.rglob('*'))
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        if actual != item['files']:
            raise RuntimeError('Frozen enhancement changed: '+item['id'])


def credentials(cell, mode):
    provider = cell['model'].split('/')[0]
    native = cell['agent'] in ('codex', 'claude-code')
    if mode == 'subscription':
        if not native:
            return 'Common harness needs API credentials; subscription mode only supports native harnesses'
        if cell['agent'] == 'claude-code':
            if not claude_token():
                return 'Missing/unexpired Claude token: use native Claude to refresh login, or claude setup-token'
        else:
            auth_path = Path(os.environ.get('CODEX_AUTH_JSON_PATH', str(Path.home()/'.codex/auth.json')))
            if not auth_path.is_file():
                return 'Missing Codex login file; run codex login'
        return None
    key = {'anthropic': 'ANTHROPIC_API_KEY', 'openai': 'OPENAI_API_KEY'}[provider]
    return None if os.environ.get(key) else f'Missing {key}'


def plans(args):
    config = read(CONFIG)
    manifest = read(MANIFEST)
    names = manifest['pilot'] if not args.all_images else [t['name'] for t in manifest['image_tasks']]
    if args.task:
        if set(args.task)-set(names):
            raise ValueError('Requested task is outside the selected cohort')
        names = args.task
    entries = {t['name']: t for t in manifest['image_tasks']}
    configs = []
    variants = [None]
    requested = getattr(args, 'enhancement', None) or []
    verify_enhancements(requested)
    if requested:
        choices = {e['id']: e for e in config['enhancements']}
        if set(requested)-set(choices):
            raise ValueError('Unknown enhancement')
        variants += [choices[e] for e in requested]
    for original in selected_cells(args):
      for enhancement in variants:
        cell = dict(original)
        cell['enhancement'] = enhancement['id'] if enhancement else 'baseline'
        if enhancement:
            cell['id'] += '--'+enhancement['id']
        scope_path = ROOT/'configs/exclusions.json'
        active_setups = read(scope_path).get('active_setups') if scope_path.exists() else None
        if active_setups is not None and cell['id'] not in active_setups:
            continue
        hosts = (['api.anthropic.com', 'claude.ai', 'platform.claude.com']
                 if cell['model'].startswith('anthropic/') else
                 ['api.openai.com', 'chatgpt.com', 'auth.openai.com'])
        for name in names:
            entry = entries[name]
            verify_task(entry)
            kwargs = {'version': cell['version']}
            if cell['agent'] == 'pi':
                kwargs['thinking'] = cell['reasoning_effort']
            else:
                kwargs['reasoning_effort'] = cell['reasoning_effort']
            if cell['agent'] == 'codex':
                kwargs['web_search'] = 'disabled'
            if cell['agent'] == 'claude-code':
                kwargs['disallowed_tools'] = 'WebSearch,WebFetch'
            job_name = f"{args.experiment}--{cell['id']}--{name}"
            task_path = enhanced_task(entry, enhancement) if enhancement else ROOT/entry['path']
            job = {'job_name': job_name, 'jobs_dir': str(ROOT/'jobs'),
                   'n_attempts': 1, 'n_concurrent_trials': 1,
                   'retry': {'max_retries': 0},
                   'agents': [{'name': cell['agent'], 'model_name': cell['model'],
                               'override_timeout_sec': config['timeout_sec'],
                               'extra_allowed_hosts': hosts, 'kwargs': kwargs}],
                   'environment': {'type': 'docker', 'delete': True},
                   'artifacts': [{'source': '/app', 'destination': 'agent-workspace',
                                  'exclude': ['__pycache__', '*.pyc']}],
                   'tasks': [{'path': str(task_path)}]}
            if enhancement and enhancement['kind'] == 'skill':
                skill = ROOT/enhancement['path']
                job['agents'][0]['skills'] = [str(skill)]
                job['extra_instructions'] = [
                    'Use the verification-before-completion skill before declaring completion. '
                    'Verify against the drawing using only agent-visible tools and files. '
                    'Hidden references and graders are not available and must not be sought.']
            if enhancement and enhancement['kind'] == 'tool':
                job['agents'][0]['env']={'MCP_TIMEOUT':'120000'}
                job['agents'][0]['mcp_servers'] = [{
                    'name': 'freecad', 'transport': 'stdio',
                    'command': '/opt/cad-bench-tools/start-freecad-mcp.sh', 'args': []}]
            from harbor.models.job.config import JobConfig
            JobConfig.model_validate(job)
            configs.append({'cell': cell, 'task': entry, 'job': job})
    return configs


def plan(args):
    rows = plans(args)
    out = ROOT/'runs'/args.experiment
    for row in rows:
        write(out/'configs'/f"{row['job']['job_name']}.json", row['job'])
    write(out/'experiment.json', {'created_at': datetime.now(timezone.utc).isoformat(),
                                 'config_sha256': sha(CONFIG), 'cohort_sha256': sha(MANIFEST),
                                 'auth_mode': args.auth, 'config': read(CONFIG),
                                 'trial_count': len(rows)})
    for row in rows:
        issue = credentials(row['cell'], args.auth)
        print(f"{row['cell']['id']:24} {row['task']['name']}  {'BLOCKED: '+issue if issue else 'credentials present (model access unverified)'}")
    print(f'{len(rows)} planned trials. No model calls made.')


def preflight(args):
    check_version()
    subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], check=True)
    failures = []
    for cell in selected_cells(args):
        issue = credentials(cell, args.auth)
        print(cell['id'] + ': ' + (issue or 'credentials present; use a pilot to verify access'))
        if issue:
            failures.append(issue)
    if MANIFEST.exists():
        for entry in read(MANIFEST)['image_tasks']:
            verify_task(entry)
        print('40 image-only task file hashes verified.')
    if failures:
        raise RuntimeError('Preflight blocked: ' + '; '.join(sorted(set(failures))))


def run(args):
    preflight(args)
    rows = plans(args)
    if args.max_trials:
        rows = rows[:args.max_trials]
    if args.auth == 'api' and args.max_cost_usd is None:
        raise ValueError('API runs require --max-cost-usd and provider-side spend limits')
    run_dir = ROOT/'runs'/args.experiment
    snapshot = {'config_sha256': sha(CONFIG), 'cohort_sha256': sha(MANIFEST)}
    existing = run_dir/'execution.json'
    if existing.exists() and any(read(existing).get(k) != v for k,v in snapshot.items()):
        raise RuntimeError('Configuration/cohort changed; start a new experiment name')
    write(existing, dict(snapshot, auth_mode=args.auth, requested_trials=len(rows)))
    completed_cost = 0.0
    for row in rows:
        job_name = row['job']['job_name']
        destination = ROOT/'jobs'/job_name
        if destination.exists():
            print('Retaining existing trial: ' + job_name)
            continue
        if args.max_cost_usd is not None and completed_cost >= args.max_cost_usd:
            raise RuntimeError('Between-trial spending limit reached')
        job = row['job']
        if args.auth == 'api' and row['cell']['agent'] == 'claude-code':
            job['agents'][0]['kwargs']['max_budget_usd'] = str(args.max_cost_usd-completed_cost)
        path = run_dir/'configs'/f'{job_name}.json'
        write(path, job)
        env = os.environ.copy()
        if args.auth == 'subscription':
            if row['cell']['agent'] == 'codex':
                env['CODEX_FORCE_AUTH_JSON'] = '1'
            else:
                env['CLAUDE_FORCE_OAUTH'] = '1'
                env['CLAUDE_CODE_OAUTH_TOKEN'] = claude_token()
        else:
            env.pop('CODEX_FORCE_AUTH_JSON', None)
            env.pop('CODEX_AUTH_JSON_PATH', None)
            env.pop('CLAUDE_FORCE_OAUTH', None)
            env.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
        print('Starting ' + job_name, flush=True)
        proc = subprocess.run([str(HARBOR), 'run', '--config', str(path)], cwd=ROOT, env=env)
        write(run_dir/'launches'/f'{job_name}.json',
              {'job_name': job_name, 'return_code': proc.returncode, 'config_sha256': sha(path)})
        costs = []
        unknown_cost = False
        for result in destination.glob('*/result.json'):
            cost = (read(result).get('agent_result') or {}).get('cost_usd')
            if cost is None:
                unknown_cost = True
            else:
                costs.append(cost)
        completed_cost += sum(costs)
        if args.auth == 'api' and (unknown_cost or not costs):
            raise RuntimeError('Cost not reported: stopping before another paid trial')
        if proc.returncode:
            raise RuntimeError('Harbor launch failed; retained output; no automatic retry')
    print('Finished selected launches; run collect and story next.')


def collect(args):
    rows = []
    expected = {r['job']['job_name']: r for r in plans(args)}
    for job_name, planned in expected.items():
        trial_files = sorted((ROOT/'jobs'/job_name).glob('*/result.json'))
        if not trial_files:
            launched=(ROOT/'jobs'/job_name).exists()
            rows.append({'task': planned['task']['name'], 'cell': planned['cell']['id'],
                         'model': planned['cell']['model'], 'agent': planned['cell']['agent'],
                         'status': 'incomplete' if launched else 'not_run', 'reward': None, 'job_name': job_name})
        for path in trial_files:
            r = read(path)
            vr = r.get('verifier_result') or {}
            rewards = vr.get('rewards') or {}
            reward = rewards.get('reward')
            exc = r.get('exception_info')
            scored = isinstance(reward, (int, float)) and not exc
            effective = float(reward) if scored else 0.0
            detail_path = path.parent/'verifier/reward_details.json'
            details = read(detail_path) if detail_path.exists() else {}
            context = r.get('agent_result') or {}
            info = r.get('agent_info') or {}
            candidate = next(iter(sorted((path.parent/'artifacts').rglob('answer.FCStd'))), None)
            artifact = {'path': str(candidate.relative_to(ROOT)), 'sha256': sha(candidate)} if candidate else None
            rows.append({'task': planned['task']['name'], 'cell': planned['cell']['id'],
                         'model': planned['cell']['model'], 'agent': planned['cell']['agent'],
                         'observed_model': (info.get('model_info') or {}).get('name'),
                         'observed_agent_version': info.get('version'),
                         'status': ('perfect' if effective >= 1.0-1e-6 else 'partial') if scored else 'error',
                         'reward': effective, 'geometry': details.get('geometry_similarity'),
                         'spec': details.get('cad_spec_consistency'), 'details': details,
                         'exception_type': (exc or {}).get('exception_type'),
                         'cost_usd': context.get('cost_usd'),
                         'input_tokens': context.get('n_input_tokens'),
                         'output_tokens': context.get('n_output_tokens'),
                         'started_at': r.get('started_at'), 'finished_at': r.get('finished_at'),
                         'candidate': artifact, 'trial_dir': str(path.parent.relative_to(ROOT)),
                         'recovery':r.get('recovery'),
                         'job_name': job_name, 'result_sha256': sha(path)})
    write(ROOT/'reports'/args.experiment/'results.json',
          {'experiment': args.experiment, 'dataset_digest': read(CONFIG)['dataset_digest'],
           'cohort_sha256': sha(MANIFEST), 'rows': rows})
    fields = ['task','cell','model','agent','status','reward','geometry','spec','cost_usd','exception_type','job_name']
    out = ROOT/'reports'/args.experiment/'results.csv'
    with out.open('w', newline='') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f'{len(rows)} rows saved to {out}')


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('prepare')
    p.add_argument('--download', action='store_true')
    p.add_argument('--count', type=int)
    p.add_argument('--replace-cohort', action='store_true')
    p.set_defaults(func=prepare)
    for name, function in [('plan', plan), ('preflight', preflight), ('run', run), ('collect', collect)]:
        p = subs.add_parser(name)
        p.add_argument('--experiment', default='pilot-3-v1')
        p.add_argument('--auth', choices=['subscription','api'], default='subscription')
        p.add_argument('--enhancement', action='append', choices=['verification-skill','freecad-mcp'])
        p.add_argument('--all-images', action='store_true')
        p.add_argument('--cell', action='append')
        p.add_argument('--task', action='append')
        if name == 'run':
            p.add_argument('--max-trials', type=int)
            p.add_argument('--max-cost-usd', type=float)
        p.set_defaults(func=function)
    args = parser.parse_args()
    try:
        args.func(args)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
