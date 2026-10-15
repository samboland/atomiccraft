import json
from pathlib import Path
import tempfile
import unittest
from explore import build


class CoverageTests(unittest.TestCase):
    def test_missing_types_and_failed_run_remain_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'properties-00'; atlas=run/'atlas'; atlas.mkdir(parents=True)
            (run/'requested-types.json').write_text(json.dumps(['Grade','Blur']))
            (run/'result.json').write_text(json.dumps({'ok':False}))
            entry={'title':'Grade initial','image':'grade.png','evidence':'grade.json'}
            (atlas/'grade.json').write_text('{}')
            (run/'atlas-manifest.json').write_text(json.dumps({'entries':[entry],'failures':[{'case':'Blur','error':'Unavailable'}]}))
            result=build(root)
            self.assertEqual(result['property_types_missing'],['Blur'])
            self.assertEqual(result['property_types_captured'],['Grade'])
            self.assertFalse(result['runs'][0]['ok'])
            self.assertEqual(len(result['failures']),1)

    def test_empty_internal_charts_are_not_capture_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'layouts'; atlas=run/'atlas'; atlas.mkdir(parents=True)
            (atlas/'chart.json').write_text(json.dumps({'widget_class':'Foundry::UI::Chart','controls':[]}))
            (run/'atlas-manifest.json').write_text(json.dumps({'entries':[{'title':'Chart','image':'chart.png','evidence':'chart.json'}],'failures':[]}))
            result=build(root)
            self.assertEqual(result['captures'],0)
            self.assertFalse(result['runs'][0]['ended'])

    def test_property_retry_recovers_initial_panel_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,entries,failures in [
                ('properties-00',[],[{'case':'Properties Blur','error':'Panel missing'}]),
                ('properties-retry',[{'title':'Blur initial','image':'blur.png','evidence':'blur.json'}],[])]:
                run=root/name; atlas=run/'atlas'; atlas.mkdir(parents=True)
                (atlas/'blur.json').write_text('{}')
                (run/'atlas-manifest.json').write_text(json.dumps({'entries':entries,'failures':failures}))
            result=build(root)
            self.assertEqual(result['unresolved_failures'],[])
            self.assertEqual(result['recovered_failures'][0]['recovered_in'],'properties-retry')

    def test_review_exclusion_keeps_run_but_removes_mislabeled_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'menus-retry'; run.mkdir()
            (root/'review-exclusions.json').write_text(json.dumps({'menus-retry':'Wrong submenu'}))
            (run/'atlas-manifest.json').write_text(json.dumps({'entries':[{'title':'Wrong'}],'failures':[]}))
            result=build(root)
            self.assertEqual(result['captures'],0)
            self.assertEqual(result['runs'][0]['excluded_reason'],'Wrong submenu')


if __name__=='__main__': unittest.main()
