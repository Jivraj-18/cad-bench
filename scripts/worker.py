#!/usr/bin/env python3
"""Persistent subscription-only benchmark queue, run by a user systemd timer."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import re
import subprocess
import time
import signal
from datetime import datetime, timezone
from pathlib import Path
import bench

ROOT=bench.ROOT


def reset_epoch(value):
    if isinstance(value,(int,float)):
        return value/1000 if value>100000000000 else float(value)
    if isinstance(value,str):
        try: return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        except ValueError: return None
    return None


def limit_details(trial,result):
    exception=(result.get('exception_info') or {}).get('exception_type','')
    texts=[];times=[];structured_rejected=False
    def scan(value):
        nonlocal structured_rejected
        if isinstance(value,dict):
            info=value.get('rate_limit_info') or value.get('rateLimitInfo')
            if isinstance(info,dict) and info.get('status')=='rejected':
                structured_rejected=True
            for k,v in value.items():
                if k in ('resetsAt','resets_at','reset_at','resetAt','retry_at'):
                    parsed=reset_epoch(v)
                    if parsed and parsed>time.time(): times.append(parsed)
                scan(v)
        elif isinstance(value,list):
            for v in value: scan(v)
    for p in (trial/'agent').rglob('*'):
        if p.is_file() and p.suffix in ('.txt','.json','.jsonl'):
            text=p.read_text(errors='replace');texts.append(text)
            for line in text.splitlines():
                try: scan(json.loads(line))
                except (ValueError,TypeError): pass
    text='\n'.join(texts).lower()
    if any(s in text for s in ('credits_required','model_requires_usage_credits','requires usage credits',
                               'unpaid invoice','no credits remaining','insufficient_quota')):
        return {'kind':'access_block','reason':'usage credits required; no automatic billing or model substitution'}
    if structured_rejected or exception in ('ApiUsageLimitError','ApiRateLimitError') or any(s in text for s in (
            "you've hit your limit", "you've hit your usage limit", 'usage_limit_reached',
            'usage limit reached','rate limit exceeded','too many requests','quota exceeded','out of usage')):
        return {'kind':'limit','reset_at':max(times)+60 if times else None,
                'reason':exception or 'provider usage/rate limit'}
    return None


def probe(cell):
    """Refresh native Claude auth and check availability without a CAD trial."""
    folder=ROOT/'runs/availability-probes';folder.mkdir(parents=True,exist_ok=True)
    if cell['agent']=='claude-code':
        cli=Path.home()/'.local/bin/claude'
        command=[str(cli),'-p','--model',cell['model'].split('/',1)[1],
                 '--max-turns','1','--tools','','--output-format','json','Reply only OK. Do not use tools.']
    else:
        cli=Path.home()/'.local/bin/codex'
        command=[str(cli),'exec','--ignore-user-config','--ignore-rules','--ephemeral',
                 '--skip-git-repo-check','-s','read-only','-C',str(folder),
                 '-m',cell['model'].split('/',1)[1],'-c','model_reasoning_effort=low',
                 'Reply only OK. Do not use tools.']
    proc=subprocess.run(command,cwd=folder,capture_output=True,text=True,timeout=180)
    # Keep diagnostic output locally; it contains no credential file contents.
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (folder/f'{cell["id"]}-{stamp}.log').write_text(proc.stdout+'\n'+proc.stderr)
    return proc.returncode==0


def unfinished_job():
    for path in (ROOT/'jobs').glob('*/result.json'):
        try: result=bench.read(path)
        except ValueError: continue
        if (result.get('stats') or {}).get('n_running_trials',0)>0:
            from recover import recover,has_owner
            if not has_owner(path.parent.name):
                if recover(path.parent):continue
            return path.parent.name
    return None


def tick(args):
    folder=ROOT/'runs'/args.experiment;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'queue.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        state_path=folder/'queue-state.json'
        state=bench.read(state_path) if state_path.exists() else {'cells':{},'retries':{},'events':[]}
        def save(event=None):
            state['updated_at']=datetime.now(timezone.utc).isoformat()
            if event: state['events'].append(dict(at=state['updated_at'],**event))
            bench.write(state_path,state)
        active=unfinished_job()
        if active:
            state['waiting_for_active_job']=active;save();return
        state.pop('waiting_for_active_job',None)
        bench.load_env();bench.check_version()
        for row in bench.plans(args):
            cell=row['cell'];base_cell=cell['id'].split('--')[0]
            if cell.get('enhancement')=='freecad-mcp':
                proof=ROOT/'runs/mcp-smoke.json'
                if not proof.exists() or bench.read(proof).get('status')!='passed':
                    save({'cell':cell['id'],'status':'waiting_for_tool_smoke_test'});continue
            cooldown=state['cells'].get(base_cell,{})
            if cooldown.get('access_block'): continue
            if cooldown.get('available_after',0)>time.time(): continue
            original=row['job']['job_name']
            attempt=state['retries'].get(original,0)
            actual=original if attempt==0 else original+f'--rescheduled-{attempt}'
            destination=ROOT/'jobs'/actual
            existing=list(destination.glob('*/result.json')) if destination.exists() else []
            if existing:
                result=bench.read(existing[0])
                limited=limit_details(existing[0].parent,result)
                if not limited:
                    continue  # Complete, or an ordinary retained failure: no retry.
                if limited['kind']=='access_block':
                    state['cells'][base_cell]={'access_block':True,'reason':limited['reason']}
                    save({'cell':base_cell,'status':'blocked_access'});continue
                if cooldown.get('failed_job') != actual:
                    state['cells'][base_cell]={'failed_job':actual,
                        'available_after':limited['reset_at'] or time.time()+3600,
                        'reported_reset':bool(limited['reset_at']), 'reason':limited['reason']}
                    save({'cell':base_cell,'status':'waiting_for_limit_reset','job':actual})
                    continue
                if not probe(cell):
                    state['cells'][base_cell]['available_after']=time.time()+3600
                    save({'cell':base_cell,'status':'availability_probe_still_blocked'});continue
                attempt+=1
                state['retries'][original]=attempt
                state['cells'][base_cell]={}
                actual=original+f'--rescheduled-{attempt}'
                destination=ROOT/'jobs'/actual
            elif destination.exists():
                # Never overwrite a partial job directory after a crash.
                save({'job':actual,'status':'incomplete_directory_retained_needs_review'});continue
            if bench.credentials(cell,'subscription'):
                if not probe(cell):
                    state['cells'][base_cell]={'available_after':time.time()+3600,'reason':'native login/availability probe failed'}
                    save({'cell':base_cell,'status':'native_auth_waiting'});continue
            job=row['job'];job['job_name']=actual
            config=folder/'configs'/f'{actual}.json';bench.write(config,job)
            env=os.environ.copy()
            # Never fall through from subscription mode into API billing.
            env.pop('OPENAI_API_KEY',None);env.pop('ANTHROPIC_API_KEY',None)
            env.pop('ANTHROPIC_AUTH_TOKEN',None)
            if cell['agent']=='codex': env['CODEX_FORCE_AUTH_JSON']='1'
            else:
                env['CLAUDE_FORCE_OAUTH']='1'
                env['CLAUDE_CODE_OAUTH_TOKEN']=bench.claude_token()
            save({'job':actual,'status':'launching','rescheduled_attempt':attempt,
                  'config_sha256':bench.sha(config)})
            logs=folder/'scheduler-logs';logs.mkdir(exist_ok=True)
            with (logs/f'{actual}.log').open('w') as output:
                proc=subprocess.Popen([str(bench.HARBOR),'run','--config',str(config)],
                                      cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,
                                      start_new_session=True)
                stopped_for_limit=False
                while proc.poll() is None:
                    time.sleep(10)
                    for trial in destination.glob('*/agent'):
                        live=limit_details(trial.parent,{})
                        if live and live['kind']=='limit':
                            save({'job':actual,'status':'stopping_at_provider_limit',
                                  'reported_reset_at':live.get('reset_at')})
                            os.killpg(proc.pid,signal.SIGINT)
                            stopped_for_limit=True
                            break
                    if stopped_for_limit:
                        try: proc.wait(timeout=180)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid,signal.SIGTERM)
                            proc.wait(timeout=60)
                        break
            save({'job':actual,'status':'launch_finished','return_code':proc.returncode,
                  'stopped_for_limit':stopped_for_limit})
            subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/bench.py'),
                'collect','--experiment',args.experiment,
                '--enhancement','verification-skill','--enhancement','freecad-mcp'],cwd=ROOT)
            subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/visuals.py'),
                '--experiment',args.experiment],cwd=ROOT)
            subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/story.py'),
                '--experiment',args.experiment],cwd=ROOT)
            return  # One trial per activation; timer runs again after completion.
        state['status']='waiting_or_finished';save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment',default='pilot-3-v1')
    p.add_argument('--enhancement',action='append',default=['verification-skill','freecad-mcp'])
    a=p.parse_args()
    a.auth='subscription';a.all_images=False;a.cell=None;a.task=None
    tick(a)
