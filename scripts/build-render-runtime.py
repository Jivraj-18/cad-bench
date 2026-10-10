#!/usr/bin/env python3
"""Build the pinned report runtime from the official verifier's dependency layers."""
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'data/cad-bench/freecad-6b54209a13/tests'
target=ROOT/'data/render-runtime'
target.mkdir(parents=True,exist_ok=True)
shutil.copytree(source/'LICENSES',target/'LICENSES',dirs_exist_ok=True)
# Exclude ALL hidden task assets. Geometry inputs are mounted after freeze.
(target/'Dockerfile').write_text((source/'Dockerfile').read_text().split('COPY grader/')[0])
subprocess.run(['docker','build','--progress=plain','-t','cad-bench-render:1.1.0',str(target)],check=True)
