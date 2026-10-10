#!/usr/bin/env python3
"""Build editable, evidence-backed static stories for every pilot drawing."""
from __future__ import annotations
import argparse
import html
import json
import shutil
import subprocess
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]


def load(path): return json.loads(Path(path).read_text())
def esc(text): return html.escape(str(text))
def score(value): return '—' if value is None else f'{float(value):.6f}'


def elapsed(row):
    if not row.get('started_at'):
        job=ROOT/'jobs'/row.get('job_name','')/'result.json'
        start=load(job).get('started_at') if job.is_file() else None
    else: start=row['started_at']
    if not start: return 'Not started' if row['status']=='not_run' else 'Unknown'
    if row.get('recovery'): return 'Incomplete accounting'
    begin=datetime.fromisoformat(start.replace('Z','+00:00'))
    if begin.tzinfo is None: begin=begin.replace(tzinfo=timezone.utc)
    finish=row.get('finished_at')
    end=datetime.fromisoformat(finish.replace('Z','+00:00')) if finish else datetime.now(timezone.utc)
    if end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
    seconds=max(0,int((end-begin).total_seconds()))
    return f'{seconds//60}m {seconds%60:02}s'+(' · in progress' if not finish else '')


def cost_label(row):
    value=row.get('cost_usd')
    return 'Not yet reported' if value is None else f'${value:.4f} reported token cost'


def milestone(arguments):
    text=(arguments if isinstance(arguments,str) else json.dumps(arguments)).lower()
    if 'all_tools' in text and 'view_image' not in text: return None
    if 'view_image' in text or 'get_view' in text: return 'Inspected drawing or model image'
    if 'isvalid' in text or 'is_valid' in text or '.solids' in text: return 'Checked solid validity'
    if 'saveas' in text or 'save_as' in text: return 'Saved a CAD version'
    if 'answer.py' in text and ('cat ' in text or 'write' in text or 'apply_patch' in text): return 'Wrote or revised the CAD script'
    if 'freecadcmd' in text and 'answer.py' in text: return 'Executed the CAD script'
    if 'execute_code' in text or 'partdesign' in text: return 'Constructed or inspected CAD features'
    return None


def process_evidence(row,report,task):
    """Publish observable actions and sampled submissions, without system prompts."""
    job=ROOT/'jobs'/row['job_name']
    trials=([ROOT/row['trial_dir']] if row.get('trial_dir') else
            [p for p in job.glob('*') if p.is_dir() and (p/'config.json').exists()])
    if not trials: return '<p>Waiting for the agent to start.</p>'
    trial=trials[0]
    target=report/'evidence'/task/row['cell'];target.mkdir(parents=True,exist_ok=True)
    actions=[];interpretations=[]
    trajectory=trial/'agent/trajectory.json'
    if trajectory.exists():
        data=load(trajectory)
        shutil.copyfile(trajectory,target/'trajectory.json')
        for step in data.get('steps',[]):
            if step.get('source')!='agent': continue
            message=step.get('message','')
            if isinstance(message,str) and any(word in message.lower() for word in (' mm','diameter','radius','fillet','chamfer')):
                interpretations.append(message)
            for call in step.get('tool_calls',[]):
                actions.append({'time':step.get('timestamp',''),'tool':call.get('function_name',''),
                                'arguments':call.get('arguments',{})})
    else:
        native=trial/'agent/codex.txt'
        if native.exists():
            for line in native.read_text(errors='replace').splitlines():
                try: event=json.loads(line)
                except ValueError: continue
                item=event.get('item') or {}
                message=item.get('text','')
                if item.get('type')=='agent_message' and any(word in message.lower() for word in (' mm','diameter','radius','fillet','chamfer')):
                    interpretations.append(message)
                if event.get('type')=='item.completed' and item.get('type') in ('command_execution','mcp_tool_call'):
                    actions.append({'time':'Timestamp not reported','tool':item.get('tool') or item['type'],
                                    'arguments':item.get('arguments') or item.get('command',''),
                                    'exit_code':item.get('exit_code'),'status':item.get('status')})
    body=''
    if interpretations:
        body+='<h3>The agent’s interpretation and modeling decisions</h3>'
        for message in interpretations:
            body+='<blockquote>'+esc(message[:2500])+'</blockquote>'
        body+='<p class="muted">These are the agent’s reported decisions. The independent comparison below checks whether the resulting CAD matches the reference.</p>'
    if actions:
        (target/'process.json').write_text(json.dumps(actions,indent=2)+'\n')
        meaningful=[]
        for action in actions:
            label=milestone({'tool':action['tool'],'arguments':action['arguments']})
            if label and (not meaningful or meaningful[-1][0]!=label):
                meaningful.append((label,action['time']))
        if meaningful:
            body+='<h3>Modeling steps observed in the logs</h3><ol>'
            for label,stamp in meaningful:
                body+=f'<li>{esc(label)} <span class="muted">{esc(stamp)}</span></li>'
            body+='</ol>'
        body+=f'<p><a href="evidence/{task}/{row["cell"]}/process.json">Download observable process log</a></p>'
    snapshots=trial/'progress/snapshots.json'
    revision_index=report/'assets'/task/row['cell']/'revisions.json'
    if revision_index.exists():
        revisions=load(revision_index)
        if len(revisions)>1:
            body+='<h3>How the saved geometry changed</h3><div class="stages">'
            for i,revision in enumerate(revisions,1):
                body+=f'<figure><img src="assets/{task}/{row["cell"]}/{revision["image"]}" alt="Saved CAD revision {i}"><figcaption>Revision {i} · {esc(revision["observed_at"])}<br>{revision["volume_mm3"]:.2f} mm³ · {revision["solid_count"]} solid(s)</figcaption></figure>'
            body+='</div><p class="muted">Actual saved revisions, displayed with a shared camera and scale. Repeated saves with unchanged geometry are omitted.</p>'
    if snapshots.exists():
        records=load(snapshots)
        cad_records=[r for r in records if r['file']=='answer.FCStd']
        if cad_records:
            shutil.copyfile(snapshots,target/'snapshots.json')
            body+='<h3>Saved CAD revisions during the run</h3><p>Sampled every 30 seconds; short-lived revisions may be missed. The final graded file is identified separately.</p><ul>'
            for record in records:
                source=snapshots.parent/record['snapshot']
                shutil.copyfile(source,target/source.name)
                if record['file']=='answer.FCStd':
                    body+=f'<li>{esc(record["observed_at"])} · <a href="evidence/{task}/{row["cell"]}/{source.name}">CAD revision</a></li>'
            body+='</ul>'
    return body


def page(title,body):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='10' fill='%231b3155'/%3E%3Cpath d='M12 44V20h40v24H12m10-8h20V28H22z' stroke='white' fill='none' stroke-width='4'/%3E%3C/svg%3E">
<script type="importmap">{{"imports":{{"three":"./lib/three.module.js"}}}}</script>
<script type="module" src="./viewer.js"></script>
<style>
:root{{--paper:#f5f2ea;--ink:#172033;--blue:#255da5;--muted:#697487}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:18px/1.65 system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:50px 24px}}h1,h2{{font-family:Georgia,serif;line-height:1.12}}h1{{font-size:clamp(2rem,5vw,4rem);max-width:950px}}h2{{font-size:2rem;margin-top:2.5rem}}
a{{color:var(--blue)}}.eyebrow,.muted{{color:var(--muted)}}.eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:13px}}
.drawing{{width:100%;max-height:720px;object-fit:contain;background:white;border:1px solid #ccc}}
.card{{padding:24px;background:white;border:1px solid #d5d0c5;margin:20px 0;border-radius:8px}}
table{{width:100%;border-collapse:collapse;font-size:15px}}td,th{{padding:12px 8px;border-bottom:1px solid #ddd;text-align:left}}.scroll{{overflow-x:auto}}
.status-perfect{{color:#25764f}}.status-error{{color:#a83d32}}.status-not_run,.status-incomplete{{color:var(--muted)}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.pair img,.stages img{{width:100%;background:white}}figure{{margin:0}}figcaption{{font-size:14px;color:var(--muted)}}
.stages{{display:flex;gap:12px;overflow-x:auto}}.stages figure{{min-width:180px;max-width:240px}}
.cad-viewer{{position:relative;border:1px solid #d5d0c5;background:#f8f8f5;border-radius:8px;overflow:hidden}}
.cad-viewer canvas{{display:block;width:100%;height:480px;touch-action:none;cursor:grab}}
.viewer-toolbar{{display:flex;gap:12px;flex-wrap:wrap;padding:14px;background:white;align-items:center}}
.viewer-toolbar select,.viewer-toolbar button{{padding:9px;font:inherit;max-width:100%}}
.viewer-labels{{display:flex;justify-content:space-around;font-size:14px;padding-top:12px}}
.viewer-labels[hidden]{{display:none}}.viewer-status{{padding:16px}}.viewer-caption{{font-size:14px;padding:0 16px}}
.viewer-panels{{display:grid;grid-template-columns:repeat(3,minmax(280px,1fr));gap:12px;padding:12px}}
.horizontal-viewer{{overflow-x:auto}}.viewer-pane h4{{margin:8px 0;text-align:center}}
.viewer-pane{{min-width:0}}.viewer-pane canvas{{height:360px;width:100%}}
.pane-toolbar{{display:flex;gap:6px}}.pane-toolbar select{{min-width:0;flex:1;width:100px}}
.pane-toolbar button,.pane-toolbar select{{padding:7px;font:14px system-ui}}
.pane-stats{{font-size:13px;line-height:1.45;min-height:3.5em;margin:8px 0}}
.wipe{{position:relative;aspect-ratio:1;background:white;max-width:700px;margin:20px auto}}.wipe img{{position:absolute;inset:0;width:100%}}.wipe .candidate{{clip-path:inset(0 calc(100% - var(--cut,50%)) 0 0)}}
input[type=range]{{width:100%;accent-color:var(--blue)}}details{{margin:16px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#ebe6da;padding:16px;font:13px/1.6 monospace}}.badge{{font:14px monospace}}
@media(max-width:650px){{.pair{{grid-template-columns:1fr}}main{{padding:30px 16px}}}}
</style></head><body><main>{body}</main></body></html>'''


def comparison(row,out,task):
    asset=out/'assets'/task/row['cell']
    base=f"assets/{task}/{row['cell']}"
    if all((asset/name).exists() for name in ('reference.mesh.json','candidate.mesh.json','alignment.json')):
        config={'reference':base+'/reference.mesh.json','candidate':base+'/candidate.mesh.json',
                'alignment':base+'/alignment.json','revisions':[]}
        index=asset/'revisions.json'
        if index.exists():
            for revision in load(index):
                config['revisions'].append({'url':base+'/'+revision['snapshot']+'.mesh.json',
                                            'observed_at':revision['observed_at']})
        (asset/'viewer.json').write_text(json.dumps(config,indent=2)+'\n')
        return f'''<h3>Inspect the CAD in your browser</h3>
<div class="cad-viewer" data-viewer="{base}/viewer.json">
<div class="viewer-toolbar"><label>View <select disabled aria-label="CAD view"></select></label>
<button class="viewer-reset" type="button">Reset view</button><span class="muted">Drag to rotate · Scroll or pinch to zoom</span></div>
<div class="viewer-status" role="status">Loading CAD geometry…</div>
<div class="viewer-labels"><span>Dataset reference</span><span>Final candidate</span></div>
<canvas aria-label="Interactive reference and candidate CAD models"></canvas><p class="viewer-caption"></p></div>
<p class="muted">The viewer displays exported mesh geometry. Reference alignment is rigid and approximate; the official score comes from the independent grader.</p>'''
    if not (asset/'reference.png').exists() or not (asset/'candidate.png').exists():
        return '<p class="muted">Matched-camera comparison has not been rendered yet.</p>'
    stages=''
    for kind in ('candidate',):
        images=sorted(asset.glob(f'{kind}-stage-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
        if images:
            model=load(asset/f'{kind}.mesh.json') if (asset/f'{kind}.mesh.json').exists() else {}
            stages+='<h3>How the final feature tree builds the part</h3><div class="stages">'
            for image in images:
                index=int(image.stem.split('-')[-1])-1
                history=model.get('stages',[])
                label=history[index].get('label',history[index].get('name','')) if index<len(history) else f'Stage {index+1}'
                stages+=f'<figure><img loading="lazy" src="{base}/{image.name}" alt="{esc(label)}"><figcaption>{esc(label)}</figcaption></figure>'
            stages+='</div><p class="muted">Feature-tree construction stages from the final file, distinct from intermediate versions saved during the run.</p>'
    return f'''<div class="pair"><figure><img src="{base}/reference.png" alt="Hidden reference model"><figcaption>Hidden reference</figcaption></figure>
<figure><img src="{base}/candidate.png" alt="Frozen candidate model"><figcaption>Frozen candidate</figcaption></figure></div>
<p>Scrub between the models. Both use one camera, one scale, and a rigid alignment.</p>
<div class="wipe" style="--cut:50%"><img src="{base}/reference.png" alt="Reference"><img class="candidate" src="{base}/candidate.png" alt="Candidate"></div>
<label>Reference / candidate comparison<input type="range" min="0" max="100" value="50" oninput="this.parentElement.previousElementSibling.style.setProperty('--cut',this.value+'%')"></label>
<p class="muted">Visualization alignment is approximate and does not change the official score.</p>{stages}'''


def horizontal_comparison(rows,report,task):
    models=[];reference=None
    for prefix,label,short in [('claude-code-opus','Claude Opus 5.5','Claude'),('codex-sol-6-1','Codex · GPT-6.1 Sol','Codex')]:
        row=next((r for r in rows if r['cell'].startswith(prefix)),None)
        if not row: continue
        asset=report/'assets'/task/row['cell'];base=f'assets/{task}/{row["cell"]}'
        if not all((asset/name).exists() for name in ('candidate.mesh.json','reference.mesh.json','alignment.json')):continue
        item={'label':label,'shortLabel':short,'url':base+'/candidate.mesh.json','alignment':base+'/alignment.json','revisions':[]}
        item['stats']={'score':score(row.get('reward')),'elapsed':elapsed(row),'cost':cost_label(row)}
        if (asset/'revisions.json').exists():
            for revision in load(asset/'revisions.json'):
                item['revisions'].append({'url':base+'/'+revision['snapshot']+'.mesh.json','observed_at':revision['observed_at']})
        models.append(item)
        reference={'label':'Dataset reference','shortLabel':'Reference','reference':True,'url':base+'/reference.mesh.json'}
    if len(models)!=2:return ''
    models.append(reference)
    asset=report/'assets'/task;asset.mkdir(parents=True,exist_ok=True)
    (asset/'comparison.json').write_text(json.dumps({'models':models},indent=2)+'\n')
    return f'''<h2>Claude, Codex, and the original CAD</h2>
<div class="cad-viewer horizontal-viewer" data-viewer="assets/{task}/comparison.json">
<p class="viewer-status" role="status">Loading the three CAD models…</p><div class="viewer-panels"></div>
<p class="viewer-caption"></p></div>
<p class="muted">Drag within a panel to rotate it; scroll or pinch to zoom. Initial alignment is rigid, with no scaling. Reference alignment is for display; official scores come from the independent grader.</p>'''


def table(rows):
    result='<div class="scroll"><table><thead><tr><th>Model / setup</th><th>Status</th><th>Geometry</th><th>Spec</th><th>Overall</th><th>Reported cost</th><th>Elapsed time</th></tr></thead><tbody>'
    for r in rows:
        cost='Unknown' if r.get('cost_usd') is None else '$'+f"{r['cost_usd']:.2f}"
        result+=f"<tr><td>{esc(r['cell'])}</td><td class=\"status-{esc(r['status'])}\">{esc(r['status'].replace('_',' '))}</td><td>{score(r.get('geometry'))}</td><td>{score(r.get('spec'))}</td><td>{score(r.get('reward'))}</td><td>{cost}</td><td>{esc(elapsed(r))}</td></tr>"
    return result+'</tbody></table></div>'


def generate(experiment):
    report=ROOT/'reports'/experiment
    shutil.copyfile(ROOT/'web/viewer.js',report/'viewer.js')
    shutil.copytree(ROOT/'web/lib',report/'lib',dirs_exist_ok=True)
    results=load(report/'results.json')
    manifest=load(ROOT/'configs/cohort.lock.json')
    entries={e['name']:e for e in manifest['image_tasks']}
    by_task=defaultdict(list)
    for r in results['rows']: by_task[r['task']].append(r)
    notes=ROOT/'stories'/experiment;notes.mkdir(parents=True,exist_ok=True)
    links=[]
    for task,rows in by_task.items():
        entry=entries[task]
        assets=report/'assets'/task;assets.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/entry['drawing'],assets/'drawing.png')
        shutil.copyfile(ROOT/entry['reference'],assets/'reference.FCStd')
        note=notes/f'{task}.md'
        if not note.exists():
            note.write_text('<!-- Add evidence-backed observations here. Regeneration preserves your edits. -->\n')
        from markdown_it import MarkdownIt
        editable=MarkdownIt('commonmark',{'html':False}).render(note.read_text())
        body=f'<a href="index.html">← All examples</a><p class="eyebrow">Drawing → reconstruction → independent verification</p><h1>Can an agent reconstruct this engineered part?</h1><p class="badge">{esc(task)}</p>'
        body+='<p class="muted">Reported token cost is the harness’s API-equivalent estimate, not a subscription charge. Missing cost remains unknown. Elapsed time includes environment setup, generation, and grading; in-progress values are live.</p>'
        shared=horizontal_comparison(rows,report,task)
        body+=f'<img class="drawing" src="assets/{task}/drawing.png" alt="Original dimensioned engineering drawing">'+shared+'<h2>The results</h2>'+table(rows)
        body+=f'<p><a href="assets/{task}/reference.FCStd">Download the dataset’s ground-truth CAD</a></p>'
        complete=[r for r in rows if r.get('reward') is not None]
        perfect=[r['cell'] for r in complete if r['status']=='perfect']
        if perfect:
            body+='<p>Official perfect-score runs: '+esc(', '.join(perfect))+'.</p>'
        elif complete:
            body+='<p>No run scored exactly 1.0.</p>'
        else:
            body+='<p>No model verdict yet. These are planned trials, not benchmark results.</p>'
        if editable.strip(): body+='<div class="card">'+editable+'</div>'
        for row in rows:
            body+=f"<section><h2>{esc(row['cell'])}</h2>"
            body+=process_evidence(row,report,task)
            if row.get('candidate'):
                if not shared:body+=comparison(row,report,task)
                cand=ROOT/row['candidate']['path']
                if cand.exists():
                    target=report/'evidence'/task/row['cell'];target.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(cand,target/'answer.FCStd')
                    script=next(iter(cand.parent.glob('answer.py')),None)
                    if script: shutil.copyfile(script,target/'answer.py')
                    (target/'score.json').write_text(json.dumps(row.get('details',{}),indent=2)+'\n')
                    body+=f'<p><a href="evidence/{task}/{row["cell"]}/answer.FCStd">Download frozen candidate CAD</a> · <a href="evidence/{task}/{row["cell"]}/score.json">Raw verifier diagnostics</a></p>'
            if row.get('details'):
                details=row['details']
                if details.get('geometry_similarity') is not None:
                    body+=f'<h3>What we got</h3><p>The final CAD scored {score(row.get("reward"))} overall: {score(details["geometry_similarity"])} for geometry and {score(details.get("cad_spec_consistency"))} for the specification checks.</p>'
                body+='<details><summary>What the official grader found</summary><pre>'+esc(json.dumps(row['details'],indent=2))+'</pre></details>'
            if row.get('exception_type'):
                body+='<p class="status-error">Run failed: '+esc(row['exception_type'])+'. Retained as zero in aggregate scoring.</p>'
            if row.get('recovery'):
                body+='<p class="muted">The Harbor driver disappeared after generation. The frozen submission was recovered and scored using the unchanged official grader in the pinned runtime. Generation was not rerun; driver return code and complete timing/cost accounting are unavailable.</p>'
            if row.get('trial_dir'):
                body+='<p class="muted">Local audit trail: '+esc(row['trial_dir'])+'. Native logs stay local; inspect them with Harbor.</p>'
            body+='</section>'
        instruction=(ROOT/entry['path']/'instruction.md').read_text()
        body+='<details><summary>Exact Harbor task instruction</summary><pre>'+esc(instruction)+'</pre></details>'
        body+='<details><summary>Method and reproducibility</summary><p>FreeCAD 1.1.0; Harbor 0.23.0; separate hidden verifier; one attempt per model/drawing; no automatic retries. This pass uses FreeCAD MCP on all three drawings. A perfect official reward is 1.0; matching dimensions alone does not establish geometric fidelity.</p><pre>'+esc(entry['package_digest'])+'</pre></details>'
        (report/f'{task}.html').write_text(page(task,body))
        links.append(f'<li><a href="{task}.html">{task}</a></li>')
    rows=results['rows'];completed=[r for r in rows if r.get('reward') is not None]
    body='<p class="eyebrow">CAD Bench V3 · image-only pilot</p><h1>Read the drawing. Build the part. Check the geometry.</h1>'
    body+=f'<p>{len(by_task)} examples · {len(completed)} completed / {len(rows)} planned trials. This pilot cannot establish a dataset-wide winner.</p><ul>'+''.join(links)+'</ul>'
    body+='<h2>Evidence before a verdict.</h2>'+table(rows)
    body+='<p>Reported costs are API-equivalent token estimates; subscription billing is not measured. Scores are from the unchanged official grader.</p>'
    body+='<p><a href="results.csv">Download results CSV</a> · <a href="results.json">Download structured results</a></p>'
    body+='<p>Stories are generated from frozen results and editable Markdown in <code>stories/'+esc(experiment)+'</code>. Rebuilding preserves your edits. Raw native trajectories and logs remain in <code>jobs/</code>.</p>'
    (report/'index.html').write_text(page('Image-to-CAD benchmark pilot',body))
    print('Report generated: '+str(report/'index.html'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',default='pilot-3-v1')
    args=parser.parse_args()
    generate(args.experiment)
