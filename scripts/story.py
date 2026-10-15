#!/usr/bin/env python3
"""Build editable, evidence-backed static stories for every pilot drawing."""
from __future__ import annotations
import argparse
import html
import json
import shutil
import subprocess
import hashlib
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]


def load(path): return json.loads(Path(path).read_text())
def esc(text): return html.escape(str(text))
def score(value):
    if value is None: return '—'
    value=float(value)
    if .9995 <= value < 1: return '>99.9%'
    if 0 < value < .0005: return '<0.1%'
    return f'{value*100:.1f}%'



EXAMPLES = {
    'freecad-f32bdb2966': 'Forked mounting bracket',
    'freecad-6b54209a13': 'Stepped enclosure',
    'freecad-f4e56c467a': 'Double-clevis mount',
}
MODELS = [('claude-code-opus', 'Claude Opus 5.5', 'claude'),
          ('codex-sol-6-1', 'GPT-6.1 Sol · Codex', 'codex')]


def quality(value, text=None):
    if value is None: return '<td>Unknown</td>'
    return f'<td data-quality="{max(0,min(1,value)):.9f}">{esc(score(value) if text is None else text)}</td>'


def score_breakdown(rows, report, task):
    body = '<section class="card"><h2>Why the score can disagree with your eyes</h2>'
    body += '<p><strong>The official score is a heuristic, not the percentage of the part that is correct.</strong> Exact material overlap measures shared solid volume; the official grader also measures surface types, mass distribution, and the positions of face centers. A different feature tree can split the same surface into different faces and lower its face-center score.</p>'
    body += '<div class="scroll"><table><thead><tr><th>Signal</th><th>Claude</th><th>Codex</th></tr></thead><tbody>'
    items=[]
    for prefix, label, slug in MODELS:
        row=next((r for r in rows if r['cell'].startswith(prefix)),None)
        if not row: return ''
        path=report/'assets'/task/row['cell']/'comparison.json'
        if not path.exists(): return ''
        items.append((row,load(path)))
    for label, values in [
        ('Official overall score', [r['reward'] for r,d in items]),
        ('Shared material / union (IoU)', [d['overlap']['volume_iou'] for r,d in items]),
        ('Geometry component (G)', [r['geometry'] for r,d in items]),
        ('Specification component (S)', [r['spec'] for r,d in items]),
    ]:
        body+='<tr><th>'+label+'</th>'+''.join(quality(v) for v in values)+'</tr>'
    body+='</tbody></table></div><p class="muted">Colors use the same 0–100% scale within these score rows. IoU is an additional diagnostic, not a replacement official score or an engineering tolerance test.</p>'
    body+='<details><summary>How the official score is calculated</summary><p><strong>Overall = 2 × G × S / (G + S)</strong>, the harmonic mean; zero if either component is zero.</p><p>After structural and bounding-box gates pass, the geometry score is:</p><pre>P = 0.10 × surface-type score + 0.35 × volume score\n  + 0.35 × surface-area score + 0.20 × principal-moment score\nG = P × (0.50 + 0.50 × face-center ICP score)</pre><p>These component scores use the grader’s tolerances; they are not raw relative differences. All six files passed the gates. For these specifications, each inconsistent or not-found check subtracts 0.1 from S (floored at zero). For example, 22/24 consistent with two not-found checks gives S = 0.8, not 22/24.</p>'
    body+='<div class="scroll"><table><tr><th>Calculation</th><th>Claude</th><th>Codex</th></tr>'
    for label,key in [('Surface-type subscore','surface_types'),('Volume subscore','volume'),('Surface-area subscore','surface_area'),('Principal-moment subscore','principal_moments'),('Face-center ICP subscore','icp')]:
        body+='<tr><th>'+label+'</th>'+''.join(quality(d['official_recomputed']['geometry_details']['subscores'][key]) for r,d in items)+'</tr>'
    for label,extract in [
        ('Property fidelity P',lambda r,d: sum(w*d['official_recomputed']['geometry_details']['subscores'][k] for k,w in [('surface_types',.1),('volume',.35),('surface_area',.35),('principal_moments',.2)])),
        ('Spatial multiplier',lambda r,d:.5+.5*d['official_recomputed']['geometry_details']['subscores']['icp']),
    ]:
        body+='<tr><th>'+label+'</th>'+''.join(quality(extract(r,d)) for r,d in items)+'</tr>'
    body+='</table></div><p>With perfect property fidelity but near-zero face-center agreement, G is about 0.5. With S = 1, that produces an overall score near 66.7%, even when material overlap is very high. This explains much of the third drawing’s apparent score gap; it does not prove every residual is a face-partition artifact.</p><p class="muted">Verified against freecad-validator 0.6.0 in the pinned scoring image: validator.py (_combine), scorers/geometry_v2.py, and the saved per-run diagnostics linked below.</p></details></section>'
    return body


def matrix(by_task):
    body='<div class="scroll"><table class="score-matrix"><thead><tr><th scope="col">Drawing</th>'
    body+=''.join(f'<th scope="col">{esc(label)}<small>High effort · FreeCAD MCP</small></th>' for prefix,label,slug in MODELS)
    body+='</tr></thead><tbody>'
    for task,rows in by_task.items():
        body+=f'<tr><th scope="row"><a href="{task}.html"><img class="matrix-thumb" src="assets/{task}/drawing.png" alt="">{esc(EXAMPLES.get(task,task))}</a><small>{esc(task)}</small></th>'
        for prefix,label,slug in MODELS:
            row=next((r for r in rows if r['cell'].startswith(prefix)),{'status':'not_run'})
            reward=row.get('reward');cost='Unknown cost' if row.get('cost_usd') is None else f"${row['cost_usd']:.2f}"
            attr='' if reward is None else f' data-quality="{reward:.9f}"'
            body+=f'<td{attr}><a class="score-link" href="{task}.html?model={slug}#comparison" aria-label="Inspect {esc(label)} on {esc(EXAMPLES.get(task,task))}, overall {score(reward)}"><strong>{score(reward)}</strong><small>{cost} · {esc(elapsed(row))}</small><span>Inspect comparison →</span></a></td>'
        body+='</tr>'
    return body+'</tbody></table></div><p class="color-legend"><span class="color-ramp"></span> 0% → 100% official score · red → green. Scores are not material-overlap percentages.</p>'


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
    viewer_version=hashlib.sha256((ROOT/'web/viewer.js').read_bytes()).hexdigest()[:12]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='10' fill='%231b3155'/%3E%3Cpath d='M12 44V20h40v24H12m10-8h20V28H22z' stroke='white' fill='none' stroke-width='4'/%3E%3C/svg%3E">
<script type="importmap">{{"imports":{{"three":"./lib/three.module.js"}}}}</script>
<script src="./lib/d3.min.js"></script>
<script type="module" src="./viewer.js?v={viewer_version}"></script>
<style>
:root{{--paper:#f5f2ea;--ink:#172033;--blue:#255da5;--muted:#697487}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:18px/1.65 system-ui,sans-serif}}
main{{max-width:1320px;margin:auto;padding:50px 24px}}h1,h2{{font-family:Georgia,serif;line-height:1.12}}h1{{font-size:clamp(2rem,5vw,4rem);max-width:950px}}h2{{font-size:2rem;margin-top:2.5rem}}
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
[data-quality]{{color:#14251d}}.score-matrix{{table-layout:fixed;font-size:16px}}.score-matrix th:first-child{{width:32%}}.score-matrix td{{padding:0;border:5px solid var(--paper)}}.score-matrix small{{display:block;font-weight:400;font-size:13px;line-height:1.5}}.score-link{{display:block;padding:24px;color:inherit;text-decoration:none}}.score-link strong{{display:block;font:700 clamp(30px,5vw,52px)/1.3 system-ui}}.score-link span{{font-size:13px;text-decoration:underline}}.score-link:hover,.score-link:focus-visible{{outline:3px solid var(--blue);outline-offset:-3px}}.matrix-thumb{{width:92px;height:65px;object-fit:contain;display:block;background:white;margin-bottom:8px}}.color-legend{{font-size:14px}}.color-ramp{{display:inline-block;width:120px;height:12px;background:linear-gradient(to right,#d73027,#ffffbf,#1a9850)}}.metric-delta{{display:block;font-size:12px}}.viewer-pane.selected-model{{outline:2px solid var(--blue);outline-offset:4px}}.replay-status{{font-size:12px;min-height:2em;margin:4px 0}}.pane-toolbar{{flex-wrap:wrap}}.viewer-toolbar label{{font-size:15px;cursor:pointer}}summary{{cursor:pointer;font-weight:600}}section[id],h2[id]{{scroll-margin-top:20px}}
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
        item['stats']={'score':score(row.get('reward')),'elapsed':elapsed(row),'cost':cost_label(row),'effort':row.get('reasoning_effort','Unknown')}
        if (asset/'comparison.json').exists():item['comparison']=base+'/comparison.json'
        if (asset/'revisions.json').exists():
            for revision in load(asset/'revisions.json'):
                item['revisions'].append({'url':base+'/'+revision['snapshot']+'.mesh.json','observed_at':revision['observed_at']})
        models.append(item)
        reference={'label':'Dataset reference','shortLabel':'Reference','reference':True,'url':base+'/reference.mesh.json'}
    if len(models)!=2:return ''
    models.append(reference)
    asset=report/'assets'/task;asset.mkdir(parents=True,exist_ok=True)
    (asset/'comparison.json').write_text(json.dumps({'models':models},indent=2)+'\n')
    return f'''<h2 id="comparison">Claude, Codex, and the original CAD</h2>
<div class="cad-viewer horizontal-viewer" data-viewer="assets/{task}/comparison.json">
<div class="viewer-toolbar"><label><input class="sync-views" type="checkbox"> Sync rotation, zoom and pan</label><span class="muted">Play construction in any panel, or choose a step.</span></div><p class="viewer-status" role="status">Loading the three CAD models…</p><div class="viewer-panels"></div>
<p class="viewer-caption"></p></div>
<p class="muted">Drag within a panel to rotate it; scroll or pinch to zoom. Initial alignment is rigid, with no scaling. Reference alignment is for display; official scores come from the independent grader.</p>'''


def deterministic_details(rows,report,task):
    ordered=[]
    for prefix,label in [('claude-code-opus','Claude'),('codex-sol-6-1','Codex')]:
        row=next((r for r in rows if r['cell'].startswith(prefix)),None)
        if row:
            p=report/'assets'/task/row['cell']/'comparison.json'
            if p.exists():ordered.append((label,row,load(p)))
    if len(ordered)!=2:return ''
    ref=ordered[0][2]['reference']
    body='<h2>Numbers behind the picture</h2><p>The official score remains unchanged. Material overlap below is an additional deterministic geometric diagnostic. In the viewer, select <strong>Missing / extra material</strong>: <strong style="color:#cf3838">red</strong> is reference material missing from the candidate; <strong style="color:#b27710">gold</strong> is extra candidate material.</p>'
    body+='<div class="scroll"><table><tr><th>Measure</th><th>Reference</th><th>Claude</th><th>Codex</th></tr>'
    for label,key in [('Volume (mm³)','volume_mm3'),('Surface area (mm²)','surface_area_mm2'),('Faces','faces'),('Edges','edges'),('Vertices','vertices')]:
        values=[ref['metrics'][key]]+[d['candidate']['metrics'][key] for _,r,d in ordered]
        body+='<tr><th>'+label+'</th><td>'+esc(f'{values[0]:,.1f}' if isinstance(values[0],float) else values[0])+'</td>'
        for v in values[1:]:
            if key in ('volume_mm3','surface_area_mm2'):
                delta=(v-values[0])/values[0]
                body+=quality(1-min(abs(delta)/.05,1),f'{v:,.1f}').replace('</td>',f'<span class="metric-delta">{delta:+.3%} vs reference</span></td>')
            else: body+='<td>'+esc(v)+'</td>'
        body+='</tr>'
    official=[d['official_recomputed']['geometry_details'] for label,r,d in ordered]
    box=official[0]['geom_details']['bbox_reference']
    body+='<tr><th>Oriented box extents (mm)</th><td>'+esc(' × '.join(f'{v:.2f}' for v in box))+'</td>'
    for detail in official:body+='<td>'+esc(' × '.join(f'{v:.2f}' for v in detail['geom_details']['bbox_candidate']))+'</td>'
    body+='</tr>'
    for label,key in [('Oriented-box difference (%)','bbox_rel_diff'),('Volume difference (%)','volume_rel_diff'),('Surface-type difference (%)','surface_types_rel_diff'),('Principal-moment difference (%)','principal_moments_rel_diff')]:
        body+='<tr><th>'+label+'</th><td>0</td>'+''.join(quality(1-min(detail['geom_details'][key]/.05,1),f'{detail["geom_details"][key]*100:.3f}%') for detail in official)+'</tr>'
    body+='<tr><th>Face-center ICP RMSE (mm)</th><td>0</td>'+''.join('<td>'+f'{detail["icp_details"]["rmse"]:.3f}'+'</td>' for detail in official)+'</tr>'
    for label,key,reference in [('Volume overlap (IoU)','volume_iou','100%'),('Missing material (mm³)','missing_material_mm3','0'),('Extra material (mm³)','extra_material_mm3','0')]:
        values=[d['overlap'][key] for _,r,d in ordered]
        body+='<tr><th>'+label+'</th><td>'+reference+'</td>'+''.join(quality(v if key=='volume_iou' else 1-min(v/ref['metrics']['volume_mm3']/.05,1),f'{v*100:.3f}%' if key=='volume_iou' else f'{v:,.1f}') for v in values)+'</tr>'
    body+='</table></div><p class="muted">For physical differences, green means 0% error and red means 5% error or more; missing/extra material uses reference volume as its denominator. IoU uses the full 0–100% scale. Face, edge and vertex counts stay uncolored: segmentation is not a physical accuracy measure. Face-center RMSE is a separate, topology-dependent measurement.</p><p class="muted">Overlap chooses the best exact solid intersection among a finite set of proper right-angle rotations, with bounding-box-center translation. It applies no scaling or reflection. It is suitable for these axis-oriented files; it is not a general optimal registration solver. The grader’s face-center ICP depends on face partitioning and is not a surface-distance measurement.</p>'
    body+='<details><summary>Inspect the saved construction trees</summary><p>These are the operations saved in the document’s feature tree. They describe construction, not the chronological editing process; actual saved revisions remain available separately.</p><div class="viewer-panels">'
    for label,data in [('Reference',ref)]+[(label,d['candidate']) for label,r,d in ordered]:
        body+=f'<div class="viewer-pane"><h3>{label}</h3><p>{data["operation_count"]} operations · {data["sketch_count"]} sketches</p><ol>'
        for operation in data['history']:
            profile=operation['profile'] or {};params=operation['parameters']
            description=operation['type'].replace('PartDesign::','')
            if 'Length' in params:description+=' · '+str(params['Length'])+' mm'
            body+=f'<li><strong>{esc(operation["label"])}</strong><br>{esc(description)}<br><span class="muted">Material change: {operation["delta_volume_mm3"]:+,.3f} mm³</span>'
            if profile.get('radii_mm'):body+='<br>Profile radii: '+esc(', '.join(str(v) for v in profile['radii_mm']))+' mm'
            body+='</li>'
        body+='</ol></div>'
    body+='</div></details><h2>Which dimension checks failed?</h2>'
    for label,row,data in ordered:
        findings=data['official_recomputed']['dimension_findings']
        body+=f'<h3>{label}</h3>'
        failed=[('Inconsistent',v) for v in findings['inconsistent']]+[('Not found',v) for v in findings['not_found']]
        if not failed:body+=f'<p>All {len(findings["consistent"])} specification checks found consistent measurements.</p>'
        else:
            body+='<div class="scroll"><table><tr><th>Parameter</th><th>Expected</th><th>Measured</th><th>Status / reason</th></tr>'
            for status,f in failed:
                body+=f'<tr><td>{esc(f["param"])}</td><td>{esc(f["spec_value"])} {esc(f["unit"])}</td><td>{esc(f.get("measured_value"))}</td><td>{status}: {esc(f.get("reason",""))}</td></tr>'
            body+='</table></div>'
        base=f'assets/{task}/{row["cell"]}'
        body+=f'<p><a href="{base}/comparison.json">Full deterministic measurements, constraints and dimension witnesses</a> · <a href="{base}/comparison-provenance.json">Input hashes and repeatability proof</a></p>'
    return body


def table(rows):
    result='<div class="scroll"><table><thead><tr><th>Model / setup</th><th>Effort</th><th>Status</th><th>Geometry</th><th>Spec</th><th>Overall</th><th>Reported cost</th><th>Elapsed time</th></tr></thead><tbody>'
    for r in rows:
        cost='Unknown' if r.get('cost_usd') is None else '$'+f"{r['cost_usd']:.2f}"
        result+=f"<tr><td>{esc(r['cell'])}</td><td>{esc(r.get('reasoning_effort','Unknown'))}</td><td class=\"status-{esc(r['status'])}\">{esc(r['status'].replace('_',' '))}</td>{quality(r.get('geometry'))}{quality(r.get('spec'))}{quality(r.get('reward'))}<td>{cost}</td><td>{esc(elapsed(r))}</td></tr>"
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
        editable=MarkdownIt('commonmark',{'html':False}).render(note.read_text()).replace('<h1>','<h2>').replace('</h1>','</h2>')
        body=f'<a href="index.html">← All examples</a><p class="eyebrow">Drawing → reconstruction → independent verification</p><h1>{esc(EXAMPLES.get(task,task))}</h1><p class="badge">{esc(task)}</p>'
        body+='<p class="muted">Reported token cost is the harness’s API-equivalent estimate, not a subscription charge. Missing cost remains unknown. Elapsed time includes environment setup, generation, and grading; in-progress values are live.</p>'
        shared=horizontal_comparison(rows,report,task)
        body+=f'<img class="drawing" src="assets/{task}/drawing.png" alt="Original dimensioned engineering drawing">'+shared+'<h2>The results</h2>'+table(rows)
        body+=f'<p><a href="assets/{task}/reference.FCStd">Download the dataset’s ground-truth CAD</a></p>'
        body+=score_breakdown(rows,report,task)
        if editable.strip(): body+='<div class="card">'+editable+'</div>'
        body+=deterministic_details(rows,report,task)
        complete=[r for r in rows if r.get('reward') is not None]
        perfect=[r['cell'] for r in complete if r['status']=='perfect']
        if perfect:
            body+='<p>Official perfect-score runs: '+esc(', '.join(perfect))+'.</p>'
        elif complete:
            body+='<p>No run scored exactly 1.0.</p>'
        else:
            body+='<p>No model verdict yet. These are planned trials, not benchmark results.</p>'
        for row in rows:
            body+=f"<details><summary>Run evidence: {esc(row['cell'])}</summary>"
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
            body+='</details>'
        instruction=(ROOT/entry['path']/'instruction.md').read_text()
        body+='<details><summary>Exact Harbor task instruction</summary><pre>'+esc(instruction)+'</pre></details>'
        body+='<details><summary>Method and reproducibility</summary><p>FreeCAD 1.1.0; Harbor 0.23.0; separate hidden verifier; one attempt per model/drawing; no automatic retries. This pass uses FreeCAD MCP on all three drawings. A perfect official reward is 1.0; matching dimensions alone does not establish geometric fidelity.</p><pre>'+esc(entry['package_digest'])+'</pre></details>'
        (report/f'{task}.html').write_text(page(EXAMPLES.get(task,task),body))
        links.append(f'<li><a href="{task}.html">{task}</a></li>')
    rows=results['rows'];completed=[r for r in rows if r.get('reward') is not None]
    body='<p class="eyebrow">CAD Bench V3 · image-only pilot</p><h1>Read the drawing. Build the part. Check the geometry.</h1>'
    body+=f'<p>{len(by_task)} drawings · {len(completed)} completed runs · one attempt per model and drawing. Select a score to inspect the model beside the reference.</p>'
    body+=matrix(by_task)
    body+='<section class="card"><h2>Useful reconstructions. Still needs an engineering check.</h2><p>Both models produced editable CAD that looks close on these three drawings. The bracket and enclosure expose consequential mistakes in Codex’s openings and cuts. On the double-clevis mount, both solids overlap the reference by more than 99.8%, despite official scores of 66–71%: face-center scoring penalizes their different surface decompositions as well as geometric residuals.</p><p><strong>Use this as a draft for inspection.</strong> These runs do not establish manufacturing readiness, fit, tolerance compliance, load capacity, or safe performance. A high visual overlap or a passed dimension check does not verify those properties. The stories show the evidence needed to review each draft.</p><p class="muted">Three drawings and one attempt per model cannot establish a dataset-wide winner or whether MCP helped. There is no baseline arm in this pilot.</p></section>'
    body+='<details><summary>Read the scoring method and cost accounting</summary><p>The unchanged official score is the harmonic mean of geometry G and specification S: 2 × G × S / (G + S). Geometry includes scalar properties and a topology-dependent face-center alignment factor; scores are not percentages of correct material. Each comparison page expands the calculation using its recorded subscores.</p><p>Reported costs are API-equivalent token estimates; subscription charges are not measured. Elapsed time includes environment setup, generation, and grading. All runs used high effort and FreeCAD MCP; the agents were not given reference geometry or grader feedback.</p></details>'
    body+='<p><a href="results.csv">Download results CSV</a> · <a href="results.json">Download structured results</a></p>'
    body+='<p>Stories are generated from frozen results and editable Markdown in <code>stories/'+esc(experiment)+'</code>. Rebuilding preserves your edits. Raw native trajectories and logs remain in <code>jobs/</code>.</p>'
    (report/'index.html').write_text(page('Image-to-CAD benchmark pilot',body))
    print('Report generated: '+str(report/'index.html'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',default='pilot-3-v1')
    args=parser.parse_args()
    generate(args.experiment)
