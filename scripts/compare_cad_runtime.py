"""Read-only deterministic CAD diagnostics; run inside the pinned FreeCAD image."""
import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path
import FreeCAD as App
import numpy as np
from freecad_validator import Validator


def clean(value):
    if isinstance(value,float):
        if not math.isfinite(value): return None
        return round(value,9)+0.0
    if isinstance(value,dict): return {str(k):clean(v) for k,v in sorted(value.items())}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,np.generic):return clean(value.item())
    return value


def mesh(shape):
    if shape.isNull() or shape.Volume<1e-7:return {'vertices':[],'triangles':[]}
    vertices,triangles=shape.tessellate(.15)
    return {'vertices':[list(v) for v in vertices],'triangles':[list(t) for t in triangles]}


def metrics(shape):
    box=shape.BoundBox
    if len(shape.Solids)!=1:raise RuntimeError('Expected one solid for mass-property comparison')
    inertia=shape.Solids[0].MatrixOfInertia
    matrix=np.array([[getattr(inertia,f'A{i+1}{j+1}') for j in range(3)] for i in range(3)])
    return {'volume_mm3':shape.Volume,'surface_area_mm2':shape.Area,
            'valid':shape.isValid(),'solid_count':len(shape.Solids),
            'faces':len(shape.Faces),'edges':len(shape.Edges),'vertices':len(shape.Vertexes),
            'sorted_axis_extents_mm':sorted([box.XLength,box.YLength,box.ZLength]),
            'principal_moments_unit_density_mm5':np.linalg.eigvalsh(matrix).tolist(),
            'surface_types':dict(sorted(Counter(type(f.Surface).__name__ for f in shape.Faces).items()))}


def sketch_details(sketch):
    if sketch is None:return None
    constraints=[]
    for i,c in enumerate(sketch.Constraints):
        constraints.append({'index':i,'type':c.Type,'value':c.Value,
                            'name':getattr(c,'Name','')})
    return {'name':sketch.Name,'label':sketch.Label,
            'geometry_types':dict(sorted(Counter(type(g).__name__ for g in sketch.Geometry).items())),
            'radii_mm':sorted(set(float(g.Radius) for g in sketch.Geometry if hasattr(g,'Radius'))),
            'constraint_count':len(constraints),'constraints':constraints,
            'fully_constrained':getattr(sketch,'FullyConstrained',None),
            'expressions':list(sketch.ExpressionEngine)}


def construction(doc,body):
    history=[];previous=0
    for obj in body.Group:
        if not obj.TypeId.startswith('PartDesign::') or not hasattr(obj,'Shape') or obj.Shape.isNull():continue
        profile=getattr(obj,'Profile',None)
        if isinstance(profile,tuple):profile=profile[0]
        params={}
        for name in ('Length','Length2','Angle','Radius','Reversed','Midplane','Refine','Type','Ruled','Closed'):
            if name in obj.PropertiesList:
                value=getattr(obj,name)
                params[name]=float(value.Value) if hasattr(value,'Value') else value
        volume=obj.Shape.Volume
        history.append({'step':len(history)+1,'name':obj.Name,'label':obj.Label,'type':obj.TypeId,
                        'profile':sketch_details(profile) if getattr(profile,'TypeId',None)=='Sketcher::SketchObject' else None,
                        'parameters':params,'depends_on':sorted(o.Name for o in obj.OutList if o.Name!=body.Name),
                        'volume_mm3':volume,'delta_volume_mm3':volume-previous,
                        'expressions':list(obj.ExpressionEngine)})
        previous=volume
    return history


def load(path):
    doc=App.openDocument(str(path))
    bodies=[o for o in doc.Objects if o.TypeId=='PartDesign::Body']
    if len(bodies)!=1 or bodies[0].Shape.isNull():raise RuntimeError('Expected exactly one nonempty PartDesign Body')
    body=bodies[0]
    return doc,body,{'metrics':metrics(body.Shape),'history':construction(doc,body),
                    'sketch_count':sum(o.TypeId=='Sketcher::SketchObject' for o in doc.Objects),
                    'operation_count':len(construction(doc,body))}


def rotations():
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((-1,1),repeat=3):
            r=np.zeros((3,3))
            for i,j in enumerate(perm):r[i,j]=signs[i]
            if np.linalg.det(r)>0:yield r


def transformed(shape,r,t):
    m=App.Matrix()
    for i in range(3):
        for j in range(3):setattr(m,f'A{i+1}{j+1}',float(r[i,j]))
    m.A14,m.A24,m.A34=map(float,t)
    result=shape.copy();result.transformShape(m)
    return result


def overlap(reference,candidate):
    """Finite pose search for these orthographic CAD files; no scaling/reflection.

    This is an explicitly limited orientation search, not a general optimal
    registration solver. It tries all four sign choices for every axis mapping
    whose sorted extent mismatch is within 15% of the best mapping.
    """
    ref_center=np.array(list(reference.BoundBox.Center));cand_center=np.array(list(candidate.BoundBox.Center))
    dims=lambda b:np.array([b.XLength,b.YLength,b.ZLength])
    ref_dims=dims(reference.BoundBox);cand_dims=dims(candidate.BoundBox)
    candidates=[]
    for r in rotations():
        mismatch=float(np.max(np.abs(np.abs(r)@cand_dims-ref_dims)/np.maximum(ref_dims,1e-12)))
        candidates.append((mismatch,r))
    threshold=min(m for m,r in candidates)+.15
    best=None;failures=[]
    for mismatch,r in candidates:
        if mismatch>threshold:continue
        t=ref_center-r@cand_center
        moved=transformed(candidate,r,t)
        try:
            common=reference.common(moved)
            if not common.isNull() and not common.isValid():raise RuntimeError('Invalid Boolean intersection')
            volume=common.Volume
        except Exception as error:
            failures.append(str(error));continue
        key=round(volume,7)
        if best is None or key>best[0]:best=(key,r,t,moved,volume)
    if best is None:raise RuntimeError('Every Boolean overlap failed: '+str(failures))
    _,r,t,moved,intersection=best
    missing=reference.cut(moved);extra=moved.cut(reference)
    for region in (missing,extra):
        if not region.isNull() and not region.isValid():raise RuntimeError('Invalid Boolean difference')
    union=reference.Volume+candidate.Volume-intersection
    return {'method':'24 proper right-angle rotations, extent shortlist, bounding-box-center translation; best exact intersection volume',
            'limitation':'Restricted to right-angle coordinate conventions; not globally optimal for arbitrary rotated models.',
            'poses_tested':sum(m<=threshold for m,r in candidates),'failed_poses':len(failures),
            'intersection_mm3':intersection,'union_mm3':union,'volume_iou':intersection/union,
            'missing_material_mm3':missing.Volume,'extra_material_mm3':extra.Volume,
            # Browser helper uses row vectors, so transpose the kernel matrix.
            'candidate_to_reference':{'rotation':r.T.tolist(),'translation':t.tolist()},
            'regions':{'missing':mesh(missing),'extra':mesh(extra)}}


def main():
    ref_path=Path('/input/reference.FCStd');cand_path=Path('/input/answer.FCStd')
    ref_doc,ref_body,ref=load(ref_path);cand_doc,cand_body,cand=load(cand_path)
    result={'schema_version':1,'freecad_version':'.'.join(App.Version()[:3]),
            'input_sha256':{'reference':hashlib.sha256(ref_path.read_bytes()).hexdigest(),
                            'candidate':hashlib.sha256(cand_path.read_bytes()).hexdigest()},
            'reference':ref,'candidate':cand,'overlap':overlap(ref_body.Shape,cand_body.Shape)}
    App.closeDocument(cand_doc.Name);App.closeDocument(ref_doc.Name)
    validator=Validator()
    geom=validator._geometry_scorer.score(str(ref_path),str(cand_path))
    spec=validator._spec_scorer.score('/input/spec.json',str(cand_path))
    findings=validator._spec_scorer._checker.check('/input/spec.json',str(cand_path))
    result['official_recomputed']={'geometry':geom.score,'spec':spec.score,
                                  'geometry_details':geom.details,'spec_details':spec.details,
                                  'dimension_findings':findings.model_dump(mode='json')}
    result['notes']=['Official face-center ICP is topology-dependent; it is not a sampled surface-distance metric.',
                     'Feature history is saved document construction order, not evidence of author editing chronology.',
                     'No agent script is executed and no CAD file is saved or corrected.']
    Path('/output/comparison.json').write_text(json.dumps(clean(result),sort_keys=True,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
