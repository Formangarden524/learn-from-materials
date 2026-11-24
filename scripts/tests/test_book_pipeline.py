"""Publication invariants using public synthetic data, no network side effects."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_pipeline as P
import test_author_book_archive as fixture
BUILDER = fixture.BUILDER

class BookPipelineTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.AuthorBookArchiveTests('test_lightweight_book_generates_readable_files_and_real_links')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.config = dict(knowledgeBase=self.f.kb, structure=self.f.structure_path,
            delivery=self.f.root/'delivery', publicDir=self.f.root/'public', stateDir=self.f.root/'state')

    def test_route_validation_and_legacy_compatibility(self):
        structure = copy.deepcopy(self.f.structure)
        BUILDER.validate_structure(structure, ['u01'])
        structure['originalStructure'][0].update(readingQuestion='为什么？', concepts=['条件', '例子'], bridge='进入下一章。')
        BUILDER.validate_structure(structure, ['u01'])
        structure['originalStructure'][0].pop('readingQuestion')
        with self.assertRaisesRegex(ValueError, 'readingQuestion'):
            BUILDER.validate_structure(structure, ['u01'])

    def test_publication_preserves_content_and_omits_private_files(self):
        (self.f.kb/'internal-review.md').write_text('Private reviewer notes')
        P.build(self.config); P.prepare(self.config)
        private = P.read(self.config['delivery']/'书籍档案/book.json')
        public = P.read(self.config['publicDir']/'书籍档案/book.json')
        self.assertEqual(private['units'], public['units'])
        self.assertEqual(public['meta']['sourcePdf'], '')
        self.assertFalse((self.config['publicDir']/'书籍档案/knowledge/internal-review.md').exists())
        self.assertNotIn(str(self.f.kb), (self.config['publicDir']/'index.html').read_text())
        self.assertTrue((self.config['publicDir']/'learning-archive.zip').is_file())

    def test_edited_output_is_not_overwritten(self):
        P.build(self.config); P.prepare(self.config)
        file = self.config['publicDir']/'index.html'; file.write_text('user edit')
        with self.assertRaisesRegex(ValueError, 'edited'):
            P.prepare(self.config)
        self.assertEqual(file.read_text(), 'user edit')

    def test_changed_generated_artifact_fails_verification(self):
        P.build(self.config)
        (self.config['delivery']/'阅读网页.html').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Changed generated'):
            P.verify(self.config)

    def test_pending_structure_cannot_deploy(self):
        P.build(self.config); P.prepare(self.config)
        with self.assertRaisesRegex(ValueError, 'not been confirmed'):
            P.deploy(self.config)

    def test_failed_privacy_check_preserves_previous_publication(self):
        P.build(self.config); P.prepare(self.config)
        previous = (self.config['publicDir']/'index.html').read_bytes()
        (self.f.kb/'units').mkdir(exist_ok=True)
        (self.f.kb/'units/u01.md').write_text('/Users/private/book.pdf')
        P.build(self.config)
        with self.assertRaisesRegex(ValueError, 'Private path'):
            P.prepare(self.config)
        self.assertEqual(previous, (self.config['publicDir']/'index.html').read_bytes())

    def test_images_are_embedded_with_correct_mime(self):
        visual = self.f.kb/'visual'; visual.mkdir()
        image = b'\xff\xd8\xffsynthetic-jpeg'
        (visual/'qc-physical-pdf-1.jpg').write_bytes(image)
        P.build(self.config); P.verify(self.config)
        html = (self.config['delivery']/'阅读网页.html').read_text()
        self.assertIn('data:image/jpeg;base64,', html)
        public = P.prepare(self.config)
        self.assertEqual(public['status'], 'public-files-prepared')

    def test_deploy_requires_fresh_browser_evidence_then_checks_online_bytes(self):
        from unittest.mock import patch
        import io
        import subprocess
        structure=copy.deepcopy(self.f.structure)
        structure.update(structureStatus='confirmed-by-user', confirmationEvidence='Synthetic confirmation')
        P.dump(self.f.structure_path,structure)
        P.build(self.config);P.prepare(self.config)
        self.config['contentReadiness']={'status':'ready','note':'Synthetic source reviewed; no external factual review.'}
        self.config['deployment']={'projectId':'prj_synthetic','projectName':'synthetic','teamId':'team_synthetic','productionUrl':'https://synthetic.vercel.app'}
        self.config['browserReview']=self.f.root/'browser.json'
        P.dump(self.config['browserReview'],dict(htmlSha256='stale',desktop=True,mobile=True,navigation=True,sources=True))
        with self.assertRaisesRegex(ValueError,'browser review'):
            P.deploy(self.config)
        P.dump(self.config['browserReview'],dict(htmlSha256=P.sha(self.config['publicDir']/'index.html'),desktop=True,mobile=True,navigation=True,sources=True))
        def cli(args,**kwargs):
            value='prj_synthetic' if args[1]=='project' else json.dumps({'deployment':{'readyState':'READY','target':'production','productionUrl':'https://synthetic.vercel.app','id':'dpl_synthetic'}})
            return subprocess.CompletedProcess(args,0,stdout=value,stderr='')
        def fetch(url,**kwargs):
            relative=P.urllib.parse.unquote(P.urllib.parse.urlparse(url).path.lstrip('/'))
            return io.BytesIO((self.config['publicDir']/relative).read_bytes())
        with patch.object(P.shutil,'which',return_value='/synthetic/vercel'),patch.object(P.subprocess,'run',side_effect=cli),patch.object(P.urllib.request,'urlopen',side_effect=fetch):
            result=P.deploy(self.config)
        self.assertEqual(result['status'],'deployed-and-verified')
        self.assertEqual(len(result['anonymousSha256Matches']),4)

    def test_paths_must_be_separate(self):
        config = dict(schemaVersion='learn-from-materials/book-pipeline-v1', knowledgeBase='input', structure='structure.json', delivery='input/output',publicDir='site',stateDir='state')
        path=self.f.root/'pipeline.json';P.dump(path,config)
        with self.assertRaisesRegex(ValueError, 'separate'):
            P.load_config(path)

if __name__ == '__main__':
    unittest.main()
