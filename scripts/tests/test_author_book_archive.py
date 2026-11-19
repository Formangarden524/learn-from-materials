"""Public synthetic fixtures for the author-led book assembler."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('author_book_builder', REPO / 'scripts/build_book_archive.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class AuthorBookArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='author-book-tests-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kb = self.root / 'input'
        (self.kb / 'unit-records').mkdir(parents=True)
        self.raw = '第一章 开始\n作者先提出问题，再用一个例子解释条件。'
        self.sid = 'source-001'
        self.record = {
            'schemaVersion': 'learn-from-materials/book-unit-v1',
            'unit': {'id': 'u01', 'label': '第一章', 'title': '先提出问题', 'source': '第一章 · PDF第1页',
                     'core': {'id': 'display-core', 'text': '作者先提出问题。'},
                     'takeaways': [{'id': 'display-takeaway', 'text': '例子保留条件。'}],
                     'conclusions': [{'title': '例子的作用', 'source': '第一章 · PDF第1页',
                                      'summary': {'id': 'display-summary', 'text': '作者用例子解释。'},
                                      'points': [{'id': 'display-point', 'text': '解释需要保留条件。'}]}]},
            'sources': [{'sourceId': self.sid, 'status': 'covered', 'reason': 'Synthetic test source'}],
            'claims': [{'id': 'claim-one', 'kind': 'definition', 'text': '测试主张',
                        'source': '第一章 · PDF第1页', 'sourceIds': [self.sid],
                        'contentIds': ['display-core', 'display-takeaway', 'display-summary', 'display-point'],
                        'evidence': [{'kind': 'text', 'sourceId': self.sid, 'quote': self.raw}]}],
            'sections': {'workedExamples': ['作者用一个例子解释条件。']},
        }
        self.write_json('unit-records/u01.json', self.record)
        (self.kb / 'full_text.txt').write_text(self.raw, encoding='utf-8')
        self.source_rows = [{'source_id': self.sid, 'source_file': 'synthetic-test-book.pdf',
                             'start_char': 0, 'end_char': len(self.raw), 'pdf_page': 1,
                             'content_sha256': hashlib.sha256(self.raw.encode()).hexdigest()}]
        self.write_json('source_map.json', self.source_rows)
        self.write_json('source_manifest.json', {'sources': [{'source_file': 'synthetic-test-book.pdf', 'sha256': '0' * 64}]})
        self.write_json('source-heading-index.json', {'entries': []})
        self.structure = {
            'bookTitle': '合成测试书', 'author': '测试作者',
            'centralQuestion': '作者怎样解释问题？', 'authorThesis': '先提出问题，再用例子解释。',
            'representativeUnitId': 'u01', 'representativeScope': '第一章，PDF第1页',
            'originalStructure': [{'chapterNumber': 1, 'title': '第一章 开始', 'pageStart': 1, 'pageEnd': 1, 'unitIds': ['u01']}],
            'attachments': [],
            'groups': [{'id': 'g-one', 'title': '提出并解释', 'chapterNumbers': [1],
                        'question': '问题如何提出？', 'summary': '作者先提出问题。',
                        'relation': '沿第一章阅读。',
                        'sources': [{'sourceId': self.sid, 'quote': '作者先提出问题'}]}],
        }
        self.structure_path = self.root / 'structure.json'
        self.structure_path.write_text(json.dumps(self.structure, ensure_ascii=False), encoding='utf-8')

    def write_json(self, relative, value):
        (self.kb / relative).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def args(self, output=None):
        return SimpleNamespace(knowledge_base=self.kb, structure=self.structure_path,
                               output_dir=output or self.root / 'delivery', source_pdf=None,
                               title=None, author=None, representative_reading=None, force=False)

    def test_lightweight_book_generates_readable_files_and_real_links(self):
        original = (self.kb / 'unit-records/u01.json').read_bytes()
        BUILDER.build(self.args())
        archive = self.root / 'delivery/书籍档案'
        for relative in ['全书档案.md', 'knowledge/INDEX.md', 'knowledge/units/u01.md']:
            file = archive / relative
            self.assertTrue(file.is_file())
            for target in re.findall(r'\]\(([^)]+)\)', file.read_text()):
                self.assertTrue((file.parent / target).is_file(), (relative, target))
        self.assertIn('解释需要保留条件。', (archive / 'knowledge/units/u01.md').read_text())
        self.assertIn('作者用一个例子解释条件。', (archive / 'knowledge/units/u01.md').read_text())
        self.assertEqual(original, (archive / 'knowledge/unit-records/u01.json').read_bytes())
        book = json.loads((archive / 'book.json').read_text())
        self.assertFalse(book['provenance']['newSemanticReview'])
        self.assertEqual(['u01'], book['provenance']['recordReviewDigests']['missingUnitIds'])
        self.assertEqual('pending-user-review', book['meta']['structureReview'])

    def test_existing_readable_files_are_preserved_byte_for_byte(self):
        (self.kb / 'units').mkdir()
        (self.kb / 'units/u01.md').write_bytes(b'# Existing unit\r\nPreserve exact bytes.\r\n')
        (self.kb / 'INDEX.md').write_bytes(b'# Existing index\r\n')
        BUILDER.build(self.args())
        copied = self.root / 'delivery/书籍档案/knowledge'
        for relative in ['INDEX.md', 'units/u01.md']:
            self.assertEqual((self.kb / relative).read_bytes(), (copied / relative).read_bytes())

    def test_nested_inputs_and_outputs_are_rejected_before_writes(self):
        original = (self.kb / 'unit-records/u01.json').read_bytes()
        for output in [self.kb, self.kb / 'delivery', self.root]:
            for force in [False, True]:
                args = self.args(output)
                args.force = force
                with self.subTest(output=output, force=force):
                    with self.assertRaisesRegex(ValueError, 'non-nested'):
                        BUILDER.build(args)
                    self.assertEqual(original, (self.kb / 'unit-records/u01.json').read_bytes())
                    self.assertFalse((output / '构建报告.json').exists())

    def test_invalid_structure_is_rejected(self):
        mutations = [
            lambda s: s.update(groups=[]),
            lambda s: s.update(representativeUnitId='missing-unit'),
            lambda s: s['groups'][0].update(chapterNumbers=[999]),
            lambda s: s['groups'].append(copy.deepcopy(s['groups'][0])),
            lambda s: s['originalStructure'].append(copy.deepcopy(s['originalStructure'][0])),
            lambda s: s.update(centralQuestion=''),
        ]
        for mutate in mutations:
            structure = copy.deepcopy(self.structure)
            mutate(structure)
            with self.subTest(structure=structure), self.assertRaises(ValueError):
                BUILDER.collect(self.kb, structure)

    def test_non_pdf_locators_are_rejected_with_existing_route_guidance(self):
        for page in [None, 0, '1']:
            rows = copy.deepcopy(self.source_rows)
            rows[0]['pdf_page'] = page
            self.write_json('source_map.json', rows)
            with self.subTest(page=page), self.assertRaisesRegex(ValueError, 'quick/systematic'):
                BUILDER.collect(self.kb, self.structure)


if __name__ == '__main__':
    unittest.main()
