import json
from pathlib import Path
import tempfile
import unittest
from catalog import build,record_path


class CoverageTests(unittest.TestCase):
    def test_pending_and_aliases_remain_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'nodes').mkdir()
            (root/'inventory.json').write_text(json.dumps({'version':'test','scope':'test',
                'candidates':[{'type':n,'sources':[]} for n in ['A','Alias','Missing']]}))
            for name in ['A','Alias']:
                record_path(root,name).write_text(json.dumps({'type':name,'class':'A','status':'captured'}))
            report=build(root)
            self.assertEqual(report['counts'],{'captured':2,'pending':1})
            self.assertEqual(report['captured_classes'],1)
            self.assertEqual(len(report['nodes']),3)

    def test_normalized_names_do_not_collide(self):
        root=Path('catalog')
        self.assertNotEqual(record_path(root,'A.B'),record_path(root,'A/B'))

    def test_failures_are_not_counted_as_captures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'nodes').mkdir()
            (root/'inventory.json').write_text(json.dumps({'version':'test','scope':'test',
                'candidates':[{'type':'Crash','sources':['registry']}]}))
            record_path(root,'Crash').write_text(json.dumps({'type':'Crash','status':'interrupted','reason':'exit'}))
            report=build(root)
            self.assertEqual(report['counts'],{'interrupted':1})
            self.assertEqual(report['captured_classes'],0)
            self.assertEqual(report['nodes'][0]['reason'],'exit')


if __name__=='__main__': unittest.main()
