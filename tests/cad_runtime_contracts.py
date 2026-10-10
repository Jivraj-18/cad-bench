"""Meaningful native-kernel contracts; execute inside the pinned render image."""
import sys
sys.path.insert(0,'/tools')
import FreeCAD as App
import Part
from compare_cad_runtime import overlap,metrics,rotations
import numpy as np

assert len(list(rotations()))==24
assert all(abs(np.linalg.det(r)-1)<1e-12 for r in rotations())

reference=Part.makeBox(10,20,30)
rotation=App.Matrix();rotation.A11=0;rotation.A12=-1;rotation.A21=1;rotation.A22=0
rotation.A14=17;rotation.A24=23;rotation.A34=-9
moved=reference.copy();moved.transformShape(rotation)
result=overlap(reference,moved)
assert abs(result['volume_iou']-1)<1e-9
assert result['missing_material_mm3']<1e-7 and result['extra_material_mm3']<1e-7

half=overlap(reference,Part.makeBox(10,20,15))
assert abs(half['volume_iou']-.5)<1e-9
assert abs(half['missing_material_mm3']-3000)<1e-7
assert half['extra_material_mm3']<1e-7

split=Part.makeBox(5,20,30).fuse(Part.makeBox(5,20,30,App.Vector(5,0,0)))
assert metrics(split)['faces']!=metrics(reference)['faces']
assert abs(overlap(reference,split)['volume_iou']-1)<1e-9
print('Native contracts passed: proper rotations, pose invariance, missing volume, and same geometry with different face partitions.')
