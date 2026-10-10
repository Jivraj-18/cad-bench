#!/usr/bin/env python3
"""Render reference/candidate with rigid alignment and shared camera and scale."""
from __future__ import annotations
import argparse
import itertools
import json
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR', '/tmp/cad-bench-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
from scipy.spatial import cKDTree


def align(reference, candidate):
    """PCA starts + rigid ICP. Never scale, deform, or reflect either object."""
    ref = np.asarray(reference,float)
    cand = np.asarray(candidate,float)
    ref = ref[np.linspace(0,len(ref)-1,min(1500,len(ref)),dtype=int)]
    cand = cand[np.linspace(0,len(cand)-1,min(1500,len(cand)),dtype=int)]
    rc,cc=ref.mean(0),cand.mean(0)
    r,c=ref-rc,cand-cc
    _,rv=np.linalg.eigh(r.T@r)
    _,cv=np.linalg.eigh(c.T@c)
    tree=cKDTree(c)
    best=(float('inf'),np.eye(3))
    for perm in itertools.permutations(range(3)):
      for signs in itertools.product((-1,1),repeat=3):
        rot=rv@np.eye(3)[:,perm]@np.diag(signs)@cv.T
        if np.linalg.det(rot)<0: continue
        for _ in range(10):
            transformed=r@rot
            _,ids=tree.query(transformed)
            target=c[ids]
            u,_,vt=np.linalg.svd(r.T@target)
            correction=np.eye(3)
            correction[2,2]=np.sign(np.linalg.det(u@vt))
            new=u@correction@vt
            if np.allclose(new,rot,atol=1e-7): break
            rot=new
        transformed=r@rot
        d1=tree.query(transformed)[0]
        d2=cKDTree(transformed).query(c)[0]
        residual=float(np.sqrt((np.mean(d1*d1)+np.mean(d2*d2))/2))
        if residual<best[0]: best=(residual,rot)
    return best[1],cc-rc@best[1],best[0]


def render(mesh,output,limits,rotation=None,translation=None,color='#919aa3'):
    v=np.asarray(mesh['vertices'],float)
    if rotation is not None: v=v@rotation+translation
    triangles=v[np.asarray(mesh['triangles'],int)]
    fig=plt.figure(figsize=(7,7),facecolor='white')
    ax=fig.add_subplot(111,projection='3d',proj_type='ortho')
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    norms=np.linalg.norm(normals,axis=1)
    normals=normals/np.maximum(norms[:,None],1e-12)
    light=np.array([-1.,-1.,2.]);light/=np.linalg.norm(light)
    brightness=.38+.62*np.maximum(0,normals@light)
    from matplotlib.colors import to_rgb
    colors=np.clip(np.array(to_rgb(color))[None,:]*brightness[:,None],0,1)
    ax.add_collection3d(Poly3DCollection(triangles,facecolors=colors,edgecolors='none',alpha=1))
    for set_limit,(lo,hi) in zip((ax.set_xlim,ax.set_ylim,ax.set_zlim),limits): set_limit(lo,hi)
    ax.set_box_aspect((1,1,1))
    ax.view_init(elev=25,azim=-55)
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    fig.savefig(output,dpi=130)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('reference')
    p.add_argument('candidate')
    p.add_argument('output')
    a=p.parse_args()
    ref=json.loads(Path(a.reference).read_text())
    cand=json.loads(Path(a.candidate).read_text())
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    rot,trans,residual=align(ref['vertices'],cand['vertices'])
    vertices=np.vstack((np.asarray(ref['vertices'])@rot+trans,cand['vertices']))
    middle=(vertices.min(0)+vertices.max(0))/2
    radius=float(np.max(vertices.max(0)-vertices.min(0))*.6)
    limits=[(x-radius,x+radius) for x in middle]
    render(ref,out/'reference.png',limits,rot,trans)
    render(cand,out/'candidate.png',limits)
    for name,model,r,t in [('reference',ref,rot,trans),('candidate',cand,None,None)]:
        for i,stage in enumerate(model.get('stages',[])):
            if not stage.get('vertices') or not stage.get('triangles'):
                continue  # Datum/binder/wire history nodes are not solid snapshots.
            render(stage,out/f'{name}-stage-{i+1}.png',limits,r,t)
    (out/'alignment.json').write_text(json.dumps({
        'method':'PCA initializations + rigid nearest-neighbour ICP; visualization only',
        'rotation':rot.tolist(),'translation':trans.tolist(),
        'surface_vertex_rmse_mm':residual,'shared_limits':limits,
        'reference_freecad_version':ref['freecad_version'],
        'candidate_freecad_version':cand['freecad_version'],
        'warning':'Approximate visualization alignment; not the official geometric scorer. No scaling or reflection.'},indent=2))


if __name__=='__main__': main()
