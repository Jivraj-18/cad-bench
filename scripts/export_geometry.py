"""Executed inside a pinned FreeCAD runtime, after candidates are frozen."""
import json
import sys
from pathlib import Path
import FreeCAD as App

input_path, output_path = sys.argv[1:3]
doc = App.openDocument(input_path)
bodies = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body']
if len(bodies) != 1 or bodies[0].Shape.isNull():
    raise RuntimeError('Expected one nonempty PartDesign Body')
body = bodies[0]

def mesh(shape):
    vertices, triangles = shape.tessellate(0.15)
    return {'vertices': [[v.x,v.y,v.z] for v in vertices],
            'triangles': [list(t) for t in triangles]}

stages = []
for obj in body.Group:
    if obj.TypeId.startswith('PartDesign::') and hasattr(obj,'Shape') and not obj.Shape.isNull():
        stages.append({'name': obj.Name, 'label': obj.Label, 'type': obj.TypeId, **mesh(obj.Shape)})
output = {'file': Path(input_path).name, 'freecad_version': '.'.join(App.Version()[:3]),
          'volume': body.Shape.Volume, 'surface_area': body.Shape.Area,
          'valid': body.Shape.isValid(), 'solid_count': len(body.Shape.Solids),
          'stages': stages, **mesh(body.Shape)}
Path(output_path).write_text(json.dumps(output))
App.closeDocument(doc.Name)
