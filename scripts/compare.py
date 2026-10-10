#!/usr/bin/env python3
"""Generate and verify deterministic reference/candidate CAD diagnostics."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',default='mcp-3-sol-v1')
    parser.add_argument('--image',default='cad-bench-render:1.1.0')
    parser.add_argument('--task',action='append')
    parser.add_argument('--cell',action='append')
    parser.add_argument('--verify-repeat',action='store_true',help='Compare byte-identical outputs from two fresh containers')
    args=parser.parse_args()
    (ROOT/'runs').mkdir(exist_ok=True)
    subprocess.run(['docker','info','--format','{{.ServerVersion}}'],check=True,capture_output=True)
    image_id=subprocess.check_output(['docker','image','inspect',args.image,'--format','{{.Id}}'],text=True).strip()
    report=ROOT/'reports'/args.experiment
    rows=json.loads((report/'results.json').read_text())['rows']
    manifest=json.loads((ROOT/'configs/cohort.lock.json').read_text())
    entries={row['name']:row for row in manifest['image_tasks']}
    for row in rows:
        if not row.get('candidate'):continue
        if args.task and row['task'] not in args.task:continue
        if args.cell and row['cell'] not in args.cell:continue
        task=entries[row['task']];source=ROOT/row['candidate']['path'];reference=ROOT/task['reference']
        reference_key=str(reference.relative_to(ROOT/task['path']))
        if sha(reference)!=task['files'][reference_key]:raise RuntimeError('Frozen dataset reference changed')
        before={str(source):sha(source),str(reference):sha(reference)}
        if before[str(source)]!=row['candidate']['sha256']:raise RuntimeError('Frozen submission changed')
        output=report/'assets'/row['task']/row['cell'];output.mkdir(parents=True,exist_ok=True)
        def run(dest):
            grader=ROOT/task['path']/'tests/grader'
            command=['docker','run','--rm','--network','none',
                '-e','PYTHONHASHSEED=0','-e','OMP_NUM_THREADS=1','-e','OPENBLAS_NUM_THREADS=1','-e','MKL_NUM_THREADS=1']
            for src,dst in [(source,'/input/answer.FCStd'),(reference,'/input/reference.FCStd'),
                            (grader/'spec.json','/input/spec.json'),(grader/'param_check.py','/input/param_check.py'),
                            (ROOT/'scripts/compare_cad_runtime.py','/tools/compare.py')]:
                command+=['--mount',f'type=bind,src={src.resolve()},dst={dst},readonly']
            command+=['--mount',f'type=bind,src={dest.resolve()},dst=/output','--entrypoint','python3',image_id,'/tools/compare.py']
            proc=subprocess.run(command,timeout=600,capture_output=True,text=True)
            if proc.returncode:raise RuntimeError('CAD comparison failed: '+proc.stderr[-3000:])
        run(output)
        diagnostic=output/'comparison.json';digest=sha(diagnostic)
        if args.verify_repeat:
            with tempfile.TemporaryDirectory(dir=ROOT/'runs') as temp:
                run(Path(temp))
                if (Path(temp)/'comparison.json').read_bytes()!=diagnostic.read_bytes():
                    raise RuntimeError('Comparison output is not byte-for-byte repeatable')
        for path,digest_before in before.items():
            if sha(Path(path))!=digest_before:raise RuntimeError('Read-only CAD input changed')
        proof={'image_id':image_id,'runtime_script_sha256':sha(ROOT/'scripts/compare_cad_runtime.py'),
               'comparison_sha256':digest,'repeat_verified':args.verify_repeat,
               'candidate_sha256':before[str(source)],'reference_sha256':before[str(reference)],
               'input_files_unchanged':True,'original_official_score':row['reward']}
        proof['reasoning_effort']=row.get('reasoning_effort','Unknown')
        proof['effort_launch_confirmed']=row.get('effort_launch_confirmed',False)
        (output/'comparison-provenance.json').write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')
        print(row['task'],row['cell'],'deterministic comparison ready; repeated:',args.verify_repeat,flush=True)


if __name__=='__main__':main()
