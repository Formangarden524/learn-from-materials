"""Public synthetic inputs verify guided-reader boundaries and safe rendering."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from render_guided import render


class GuidedReadingTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'examples/guided-reading-example.json').read_text())
        self.template = (ROOT / 'templates/guided-reader.html').read_text()

    def test_document_uses_its_actual_scope_and_keeps_quotes(self):
        output, report = render(self.data, self.template)
        self.assertIn('原文标题', output)
        self.assertNotIn('第一章的指定部分', output)
        self.assertNotIn('作者章名', output)
        self.assertIn(self.data['presentation']['representativeScope'], output)
        payload = output.split('<script id="content-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload), self.data)
        self.assertEqual(report['quoteCheck'], 'not-run')
        self.assertEqual(report['semanticReview'], 'not-performed-by-renderer')

    def test_unknown_source_reference_is_rejected(self):
        self.data['sections'][0]['sourceIds'] = ['missing']
        with self.assertRaisesRegex(ValueError, 'Unknown quote'):
            render(self.data, self.template)

    def test_editorial_route_cannot_be_labelled_as_author_framework(self):
        self.data['spine'][0]['evidence'] = 'material'
        with self.assertRaisesRegex(ValueError, 'editorial synthesis'):
            render(self.data, self.template)

    def test_original_source_check_rejects_an_altered_quote(self):
        original = self.data['quotes'][0]['text']
        self.data['quotes'][0]['sourceBlockId'] = 'source-one'
        mapping = [{'source_id': 'source-one', 'start_char': 0, 'end_char': len(original)}]
        _, report = render(self.data, self.template, mapping, original)
        self.assertEqual(report['quotesCheckedAgainstOriginal'], 1)
        self.data['quotes'][0]['text'] += '这句不在原文。'
        with self.assertRaisesRegex(ValueError, 'continuous original substring'):
            render(self.data, self.template, mapping, original)

    def test_literal_script_markup_stays_inside_data(self):
        self.data['sections'][0]['explanation'] = '</script><script>throw new Error("bad")</script>'
        self.data['presentation']['detailHeading'] = '`name()` 与 ${value}'
        output, _ = render(self.data, self.template)
        self.assertEqual(output.count('<script'), 2)
        self.assertNotIn('<script>throw', output)
        self.assertIn('\\u003c/script>', output)


if __name__ == '__main__':
    unittest.main()
