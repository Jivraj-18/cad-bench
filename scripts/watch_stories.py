#!/usr/bin/env python3
"""Observe existing Harbor trials, retain changed /app submissions, rebuild stories.

This launches no agents and installs no daemon. Snapshots are sampled, not a
complete history of every transient file. Official grading uses final artifacts.
"""
import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / '.venv/bin/python')


def snapshot(job):
    trials = [p for p in job.iterdir() if p.is_dir() and (p/'config.json').exists()]
    containers = subprocess.run(['docker','ps','--format','{{.Names}}'],
                                capture_output=True,text=True,timeout=20)
    for trial in trials:
        names = [n for n in containers.stdout.splitlines()
                 if n.startswith(trial.name.lower()+'__env-main-')]
        if not names:
            continue
        folder = trial/'progress'; folder.mkdir(exist_ok=True)
        index = folder/'snapshots.json'
        records = json.loads(index.read_text()) if index.exists() else []
        for filename in ('answer.py','answer.FCStd'):
            temporary = folder/('.current-'+filename)
            copied = subprocess.run(['docker','cp',names[0]+':/app/'+filename,str(temporary)],
                                    capture_output=True,timeout=30)
            if copied.returncode or not temporary.exists():
                continue
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            if any(r['file']==filename and r['sha256']==digest for r in records):
                temporary.unlink(); continue
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            target = folder/(stamp+'-'+filename)
            temporary.rename(target)
            records.append({'file':filename,'snapshot':target.name,'sha256':digest,
                            'observed_at':datetime.now(timezone.utc).isoformat(),
                            'source':'sampled from agent-visible /app; not the final graded artifact'})
        index.write_text(json.dumps(records,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',required=True)
    parser.add_argument('--interval',type=int,default=30)
    parser.add_argument('--expected-trials',type=int,default=6)
    args=parser.parse_args()
    while True:
        jobs=list((ROOT/'jobs').glob(args.experiment+'--*--freecad-mcp--*'))
        for job in jobs:
            try: snapshot(job)
            except (OSError,subprocess.TimeoutExpired,ValueError) as error:
                print('Snapshot unavailable:',job.name,type(error).__name__,flush=True)
        subprocess.run([PYTHON,str(ROOT/'scripts/bench.py'),'collect','--experiment',args.experiment,
                        '--enhancement','freecad-mcp'],cwd=ROOT,check=True)
        subprocess.run([PYTHON,str(ROOT/'scripts/story.py'),'--experiment',args.experiment],
                       cwd=ROOT,check=True)
        results=[p for job in jobs for p in job.glob('*/result.json')]
        if len(jobs)>=args.expected_trials and len(results)>=args.expected_trials:
            subprocess.run([PYTHON,str(ROOT/'scripts/visuals.py'),'--experiment',args.experiment],cwd=ROOT)
            subprocess.run([PYTHON,str(ROOT/'scripts/story.py'),'--experiment',args.experiment],cwd=ROOT,check=True)
            print('All selected attempts ended; stories updated. No automatic reruns.',flush=True)
            return
        time.sleep(args.interval)


if __name__=='__main__': main()
