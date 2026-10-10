#!/usr/bin/env python3
"""Export and render frozen candidates in a separate offline container."""
import argparse
import json
import subprocess
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def render_revisions(row,target,image):
    """Show actual sampled geometry changes, omitting repeated saved geometry."""
    if not row.get('trial_dir'): return
    folder=ROOT/row['trial_dir']/'progress'
    index=folder/'snapshots.json'
    if not index.exists(): return
    from render import render
    import numpy as np
    revisions=[];seen=set()
    for record in json.loads(index.read_text()):
        if record['file']!='answer.FCStd': continue
        mesh_path=target/(record['snapshot']+'.mesh.json')
        try: export(folder/record['snapshot'],mesh_path,image)
        except subprocess.CalledProcessError:
            continue  # Incomplete saves stay downloadable; cannot render a solid yet.
        mesh=json.loads(mesh_path.read_text())
        key=hashlib.sha256(json.dumps([mesh['vertices'],mesh['triangles']],sort_keys=True).encode()).hexdigest()
        if key in seen: continue
        seen.add(key);revisions.append((record,mesh))
    if not revisions: return
    vertices=np.vstack([np.asarray(m['vertices']) for _,m in revisions])
    final=target/'candidate.mesh.json'
    if final.exists(): vertices=np.vstack([vertices,np.asarray(json.loads(final.read_text())['vertices'])])
    middle=(vertices.min(0)+vertices.max(0))/2
    radius=float(np.max(vertices.max(0)-vertices.min(0))*.6)
    limits=[(v-radius,v+radius) for v in middle]
    rendered=[]
    for number,(record,mesh) in enumerate(revisions,1):
        filename=f'revision-{number}.png'
        render(mesh,target/filename,limits)
        rendered.append(dict(record,image=filename,volume_mm3=mesh['volume'],
                             solid_count=mesh['solid_count'],valid=mesh['valid']))
    (target/'revisions.json').write_text(json.dumps(rendered,indent=2)+'\n')


def gui_render(row,reference,candidate,target):
    """Replace mesh previews with the native depth-buffered CAD renderer."""
    alignment=json.loads((target/'alignment.json').read_text())
    limits=alignment['shared_limits']
    items=[{'path':'/input/reference.FCStd','output':'reference.png',
            'rotation':alignment['rotation'],'translation':alignment['translation']},
           {'path':'/input/candidate.FCStd','output':'candidate.png',
            'stages':True,'prefix':'candidate'}]
    mounts=['--mount',f'type=bind,src={reference.resolve()},dst=/input/reference.FCStd,readonly',
            '--mount',f'type=bind,src={candidate.resolve()},dst=/input/candidate.FCStd,readonly']
    index=target/'revisions.json'
    if index.exists():
        revisions=json.loads(index.read_text())
        folder=ROOT/row['trial_dir']/'progress'
        for i,revision in enumerate(revisions):
            path=f'/input/revision-{i}.FCStd'
            mounts+=['--mount',f'type=bind,src={(folder/revision["snapshot"]).resolve()},dst={path},readonly']
            items.append({'path':path,'output':revision['image']})
    config={'center':[(lo+hi)/2 for lo,hi in limits],'radius':(limits[0][1]-limits[0][0])/2,'items':items}
    (target/'gui-render.json').write_text(json.dumps(config,indent=2)+'\n')
    subprocess.run(['docker','run','--rm','--network','none',*mounts,
        '--mount',f'type=bind,src={target.resolve()},dst=/output',
        '--mount',f'type=bind,src={ROOT/"tools/render-cad.FCMacro"},dst=/tools/render.FCMacro,readonly',
        '--entrypoint','xvfb-run','cad-bench-mcp-smoke:1.1.0','-a','freecad','/tools/render.FCMacro'],
        check=True,timeout=120)
    status=json.loads((target/'gui-render-status.json').read_text())
    if status.get('status')!='passed': raise RuntimeError('CAD GUI rendering failed: '+str(status))


def export(source,dest,image):
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists(): return
    subprocess.run(['docker','run','--rm','--network','none',
                    '--mount',f'type=bind,src={source.resolve()},dst=/input/model.FCStd,readonly',
                    '--mount',f'type=bind,src={dest.parent.resolve()},dst=/output',
                    '--mount',f'type=bind,src={ROOT / "scripts/export_geometry.py"},dst=/tools/export.py,readonly',
                    '--entrypoint','python3',image,'/tools/export.py','/input/model.FCStd',
                    '/output/'+dest.name],check=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment',default='pilot-3-v1')
    p.add_argument('--image',default='cad-bench-render:1.1.0')
    p.add_argument('--gui',action='store_true',help='Optional native GUI screenshots; mesh export does not require them')
    a=p.parse_args()
    manifest=json.loads((ROOT/'configs/cohort.lock.json').read_text())
    entries={t['name']:t for t in manifest['image_tasks']}
    report=ROOT/'reports'/a.experiment
    results=json.loads((report/'results.json').read_text())
    for row in results['rows']:
        if not row.get('candidate'): continue
        target=report/'assets'/row['task']/row['cell']
        ref=target/'reference.mesh.json';candidate=target/'candidate.mesh.json'
        export(ROOT/entries[row['task']]['reference'],ref,a.image)
        export(ROOT/row['candidate']['path'],candidate,a.image)
        subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/render.py'),
                        str(ref),str(candidate),str(target)],check=True)
        render_revisions(row,target,a.image)
        if a.gui:
            gui_render(row,ROOT/entries[row['task']]['reference'],ROOT/row['candidate']['path'],target)


if __name__=='__main__': main()
