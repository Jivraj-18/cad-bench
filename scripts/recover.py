#!/usr/bin/env python3
"""Recover a finished container submission after its Harbor driver disappears.

Generation is never rerun. The exact official test.sh and grader files execute
in the separately built, pinned FreeCAD 1.1.0 verifier runtime. Recovery is
explicitly identified in both the trial record and a provenance manifest.
"""
import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import bench

ROOT=bench.ROOT


def has_owner(job_name):
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if p.stat().st_uid!=os.getuid():continue
            parts=(p/'cmdline').read_bytes().decode(errors='replace').split('\0')
        except OSError:continue
        if any(x.endswith('/harbor') for x in parts[:3]) and 'run' in parts:
            if any(job_name in x for x in parts):return True
        if any(x.endswith('scripts/bench.py') for x in parts[:3]) and 'run' in parts:
            return True
    return False


def recover(job_path):
    from harbor.models.trial.result import TrialResult,AgentInfo,ModelInfo
    from harbor.models.trial.config import TrialConfig
    from harbor.models.agent.context import AgentContext
    from harbor.models.verifier.result import VerifierResult
    from harbor.models.task.id import LocalTaskId
    job=Path(job_path).resolve()
    if has_owner(job.name):return False
    trials=[p.parent for p in job.glob('*/config.json') if not (p.parent/'result.json').exists()]
    for trial in trials:
        cfg=bench.read(trial/'config.json');task=Path(cfg['task']['path'])
        # Only adopt confirmed successful terminal agent output.
        terminal=False;usage={}
        for path in (trial/'agent').glob('*.txt'):
            for line in path.read_text(errors='replace').splitlines():
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('type')=='turn.completed':terminal=True;usage=event.get('usage',{})
                if event.get('type')=='result' and not event.get('is_error',True):terminal=True
        if not terminal:return False
        names=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
        container=next((n for n in names if n.startswith(trial.name.lower()+'__env-main-')),None)
        if not container:return False
        artifacts=trial/'artifacts';artifacts.mkdir(exist_ok=True)
        recovered=artifacts/'recovered-app'
        subprocess.run(['docker','cp',container+':/app',str(recovered)],check=True)
        canonical=artifacts/'app';canonical.mkdir(exist_ok=True)
        for name in ('answer.py','answer.FCStd'):
            shutil.copyfile(recovered/name,canonical/name)
        native=trial/'agent/native-sessions'
        native_copy=subprocess.run(['docker','cp',container+':/tmp/codex-home/sessions',str(native)],capture_output=True)
        provenance={'kind':'orphaned_harbor_driver_after_generation',
                    'generation_rerun':False,'native_driver_return_code':'unavailable',
                    'candidate_sha256':bench.sha(canonical/'answer.FCStd'),
                    'script_sha256':bench.sha(canonical/'answer.py'),
                    'native_sessions_recovered':native_copy.returncode==0,
                    'official_test_sha256':bench.sha(task/'tests/test.sh'),
                    'runtime_image':'cad-bench-render:1.1.0',
                    'recovered_at':datetime.now(timezone.utc).isoformat()}
        verifier=trial/'verifier';verifier.mkdir(exist_ok=True)
        command=['docker','run','--rm','--network','none',
                 '--mount',f'type=bind,src={canonical},dst=/app,readonly',
                 '--mount',f'type=bind,src={task / "tests"},dst=/tests,readonly',
                 '--mount',f'type=bind,src={task / "tests/grader"},dst=/opt/grader,readonly',
                 '--mount',f'type=bind,src={verifier},dst=/logs/verifier',
                 '--entrypoint','bash','cad-bench-render:1.1.0','/tests/test.sh']
        with (verifier/'test-stdout.txt').open('w') as out,(verifier/'test-stderr.txt').open('w') as err:
            proc=subprocess.run(command,stdout=out,stderr=err,timeout=600)
        provenance['verifier_return_code']=proc.returncode
        if proc.returncode:raise RuntimeError('Recovered official verifier failed; evidence retained')
        rewards=bench.read(verifier/'reward.json')
        lock=bench.read(trial/'lock.json')
        parent=bench.read(job/'result.json')
        model=cfg['agent']['model_name'];provider,model_id=model.split('/',1)
        result=TrialResult(
            task_name=task.name,trial_name=trial.name,trial_uri=trial.as_uri(),
            task_id=LocalTaskId(path=task),task_checksum=lock['task']['digest'],
            config=TrialConfig.model_validate(cfg),
            agent_info=AgentInfo(name=cfg['agent']['name'],
                                 version=cfg['agent']['kwargs']['version'],
                                 model_info=ModelInfo(name=model_id,provider=provider)),
            agent_result=AgentContext(n_input_tokens=usage.get('input_tokens'),
                                      n_cache_tokens=usage.get('cached_input_tokens'),
                                      n_output_tokens=usage.get('output_tokens'),cost_usd=None),
            verifier_result=VerifierResult(rewards=rewards),
            verifier_environment_mode='separate',
            started_at=parent.get('started_at'),finished_at=datetime.now(timezone.utc))
        payload=result.model_dump(mode='json');payload['recovery']=provenance
        bench.write(trial/'recovery.json',provenance)
        bench.write(trial/'result.json',payload)
        backup=job/'pre-recovery-result.json'
        if not backup.exists():shutil.copyfile(job/'result.json',backup)
        parent['stats']['n_running_trials']=0
        parent['stats']['n_completed_trials']=1
        parent['finished_at']=payload['finished_at'];parent['recovery']=provenance
        bench.write(job/'result.json',parent)
        # These are this trial's orphan containers, not unrelated services.
        related=[n for n in names if n.startswith(trial.name.lower()+'__env-')]
        if related:subprocess.run(['docker','stop',*related],check=True,capture_output=True)
        print('Recovered frozen submission and official reward:',rewards,flush=True)
        return True
    return False


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('job_path')
    a=p.parse_args();recover(a.job_path)
