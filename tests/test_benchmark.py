import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bench=module('bench',ROOT/'scripts/bench.py')
renderer=module('renderer',ROOT/'scripts/render.py')
story=module('story',ROOT/'scripts/story.py')


class Contracts(unittest.TestCase):
    def test_scores_do_not_round_imperfect_runs_to_perfect(self):
        self.assertEqual(story.score(.999873),'>99.9%')
        self.assertEqual(story.score(1),'100.0%')
        self.assertEqual(story.score(0),'0.0%')
        self.assertEqual(story.score(None),'—')

    def test_matrix_keeps_unknown_score_and_cost_unknown(self):
        markup=story.matrix({'example':[{'cell':'claude-code-opus--freecad-mcp','status':'not_run'}]})
        self.assertIn('Unknown cost',markup)
        self.assertNotIn('data-quality="0',markup)
        self.assertIn('?model=claude#comparison',markup)
        self.assertIn('?model=codex#comparison',markup)

    def test_story_time_accepts_harbor_naive_and_utc_timestamps(self):
        for start in ('2026-10-10T10:00:00','2026-10-10T10:00:00Z'):
            row={'status':'partial','started_at':start,'finished_at':'2026-10-10T10:02:15Z'}
            self.assertEqual(story.elapsed(row),'2m 15s')

    def test_story_filters_routine_commands_and_preserves_modeling_actions(self):
        self.assertIsNone(story.milestone('ls -la /app'))
        self.assertIsNone(story.milestone('print(ALL_TOOLS)'))
        self.assertEqual(story.milestone('body.Shape.isValid(); len(body.Shape.Solids)'),
                         'Checked solid validity')
        self.assertEqual(story.milestone('doc.saveAs("/app/answer.FCStd")'),'Saved a CAD version')

    def test_missing_cost_is_not_zero(self):
        self.assertEqual(story.cost_label({}),'Not yet reported')
        self.assertIn('$0.0000',story.cost_label({'cost_usd':0}))

    def test_only_drawing_tasks_with_separate_verifier_are_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task=root/'freecad-example';(task/'environment').mkdir(parents=True)
            (task/'instruction.md').write_text('The drawing is your only source of geometry.')
            (task/'environment/example.png').write_bytes(b'image')
            (task/'task.toml').write_text('[task]\nname="gnucleus-ai/freecad-example"\n[verifier]\nenvironment_mode="separate"\n')
            with patch.object(bench,'ROOT',root):
                row=bench.drawing_task(task)
                self.assertEqual(row['name'],'freecad-example')
                (task/'environment/second.png').write_bytes(b'bad extra image')
                with self.assertRaisesRegex(RuntimeError,'unexpected drawing'):
                    bench.drawing_task(task)
                (task/'instruction.md').write_text('Create this part from a text description.')
                self.assertIsNone(bench.drawing_task(task))

    def test_changed_frozen_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task=root/'task';task.mkdir();path=task/'instruction.md';path.write_text('original')
            row={'name':'task','path':'task','files':{'instruction.md':bench.sha(path)}}
            path.write_text('contaminated')
            with patch.object(bench,'ROOT',root):
                with self.assertRaisesRegex(RuntimeError,'changed after freeze'):
                    bench.verify_task(row)

    def test_pending_and_failed_trials_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'config.json';manifest=root/'cohort.json'
            config.write_text(json.dumps({'dataset_digest':'sha256:test'}));manifest.write_text('{}')
            planned=[]
            for name in ('not-started','failed','almost-perfect'):
                planned.append({'task':{'name':'task'},'cell':{'id':name,'model':'model','agent':'codex'},'job':{'job_name':name}})
            for name,result in [('failed',{'exception_info':{'exception_type':'ApiError'}}),
                                ('almost-perfect',{'verifier_result':{'rewards':{'reward':0.999873}}})]:
                p=root/'jobs'/name/'trial';p.mkdir(parents=True)
                (p/'result.json').write_text(json.dumps(result))
            args=argparse.Namespace(experiment='test')
            with patch.multiple(bench,ROOT=root,CONFIG=config,MANIFEST=manifest),patch.object(bench,'plans',return_value=planned):
                bench.collect(args)
            rows=json.loads((root/'reports/test/results.json').read_text())['rows']
            by={r['cell']:r for r in rows}
            self.assertIsNone(by['not-started']['reward'])
            self.assertEqual(by['not-started']['status'],'not_run')
            self.assertEqual(by['failed']['reward'],0)
            self.assertEqual(by['failed']['status'],'error')
            self.assertEqual(by['almost-perfect']['status'],'partial')

    def test_rigid_alignment_preserves_scale_and_orientation(self):
        rng=np.random.default_rng(7)
        reference=rng.normal(size=(80,3))*[1,3,7]
        angle=.7
        rotation=np.array([[np.cos(angle),-np.sin(angle),0],
                           [np.sin(angle),np.cos(angle),0],[0,0,1]])
        candidate=reference@rotation+[14,8,-6]
        r,t,error=renderer.align(reference,candidate)
        self.assertAlmostEqual(np.linalg.det(r),1,places=7)
        np.testing.assert_allclose(r.T@r,np.eye(3),atol=1e-7)
        self.assertLess(error,1e-6)
        np.testing.assert_allclose(reference@r+t,candidate,atol=1e-6)


if __name__=='__main__':unittest.main()
