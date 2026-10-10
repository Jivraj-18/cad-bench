#!/usr/bin/env python3
"""Build GitHub Pages HTML and a separate, audited R2 data upload directory."""
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def rewrite(text,base):
    return re.sub(r'((?:src|href|data-viewer)=")((?:assets/|evidence/)[^"]+|results\.(?:json|csv))(")',
                  lambda m:m[1]+base+'/'+m[2]+m[3],text)


def build(experiment,base):
    report=ROOT/'reports'/experiment
    data=ROOT/'dist/r2/cad-bench'/experiment
    pages=ROOT/'docs'
    data.mkdir(parents=True,exist_ok=True);pages.mkdir(exist_ok=True)
    for name in ('viewer.js','lib'):
        source=report/name
        if source.is_dir(): shutil.copytree(source,pages/name,dirs_exist_ok=True)
        else: shutil.copyfile(source,pages/name)
    base=base.rstrip('/')+'/cad-bench/'+experiment
    files=[]
    for source in report.rglob('*'):
        if not source.is_file(): continue
        relative=source.relative_to(report)
        if relative.parts[0]=='lib' or source.name=='viewer.js': continue
        if source.suffix=='.html':
            (pages/source.name).write_text(rewrite(source.read_text(),base));continue
        # Full native trajectories contain system context and image payloads;
        # they stay in local jobs/, separate from this public evidence bundle.
        if source.name=='trajectory.json': continue
        if source.suffix not in ('.json','.csv','.png','.FCStd','.py'): continue
        if source.name.startswith('gui-render') or source.name.startswith('reference-stage-') or source.name.startswith('candidate-stage-'): continue
        target=data/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix=='.json':
            document=json.loads(source.read_text())
            if source.name=='viewer.json':
                document['reference']=base+'/'+document['reference']
                document['candidate']=base+'/'+document['candidate']
                document['alignment']=base+'/'+document['alignment']
                for revision in document['revisions']: revision['url']=base+'/'+revision['url']
            if source.name=='comparison.json':
                for model in document['models']:
                    model['url']=base+'/'+model['url']
                    if model.get('alignment'):model['alignment']=base+'/'+model['alignment']
                    for revision in model.get('revisions',[]):revision['url']=base+'/'+revision['url']
            target.write_text(json.dumps(document,separators=(',',':'))+'\n')
        else: shutil.copyfile(source,target)
        files.append({'path':str(relative),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                      'bytes':target.stat().st_size,'url':base+'/'+str(relative)})
    (pages/'.nojekyll').touch()
    manifest={'experiment':experiment,'built_at':datetime.now(timezone.utc).isoformat(),
              'data_base':base,'viewer':'Three.js 0.186.1; static mesh display only',
              'submitted_cad_modified':False,'raw_native_logs_public':False,'files':files}
    (data/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (ROOT/'configs/publication.json').write_text(json.dumps({
        'repo':'Jivraj-18/cad-bench','pages':'https://jivraj-18.github.io/cad-bench/',
        'experiment':experiment,'r2_directory':'~/r2/cad-bench',
        'r2_base':base,'three_version':'0.186.1'},indent=2)+'\n')
    print(f'Built {len(list(pages.glob("*.html")))} pages and {len(files)} R2 data files ({sum(f["bytes"] for f in files)/1024/1024:.1f} MiB).')
    print('Stage directory:',data)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment',default='mcp-3-sol-v1')
    p.add_argument('--r2-base',required=True)
    args=p.parse_args();build(args.experiment,args.r2_base)
