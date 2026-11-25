"""Interrupted/resumed source access must not manufacture full-book completion."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_context as C
import book_pipeline as P
import test_author_book_archive as fixture


class BookContextTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.AuthorBookArchiveTests('test_lightweight_book_generates_readable_files_and_real_links')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root, self.kb = self.f.root, self.f.kb
        text = self.f.raw * 20
        (self.kb / 'full_text.txt').write_text(text)
        row = self.f.source_rows[0]; row.update(end_char=len(text), content_sha256=hashlib.sha256(text.encode()).hexdigest())
        self.f.write_json('source_map.json', [row])
        self.config_path = self.root / 'pipeline.json'
        self.cfg = dict(schemaVersion='learn-from-materials/book-pipeline-v1', knowledgeBase=str(self.kb),
                        structure=str(self.f.structure_path), delivery=str(self.root/'delivery'),
                        publicDir=str(self.root/'public'), stateDir=str(self.root/'publication-state'))
        self.config_path.write_text(json.dumps(self.cfg))
        self.project = C.initialize(self.config_path, self.root/'context')

    def read_all(self):
        receipts = []
        while True:
            chunk = C.next_read(self.project, 80)
            if 'receipt' not in chunk: break
            receipts.append(chunk['receipt'])
            C.mutate(self.project, 'ack-read', receipt=chunk['receipt'], note='Read the returned synthetic paragraph in full.')
        return receipts

    def review_chapter(self):
        C.mutate(self.project, 'checkpoint', chapter='chapter-1', note='Canonical explanation and its conditions saved.')
        for phase in ('source', 'content'):
            C.mutate(self.project, 'review-chapter', chapter='chapter-1', phase=phase, note='Reread source and checked all synthetic content/conditions: '+phase)

    def finish(self):
        self.read_all(); self.review_chapter()
        C.mutate(self.project, 'review-book', note='All original sections, independent content and key figures checked; synthetic source has no figures.')

    def test_import_does_not_inherit_covered_as_read(self):
        self.assertEqual(C.packet(self.project)['progress'], '0/1 source pages')
        self.assertEqual(C.audit(self.project)['status'], 'incomplete')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            C.initialize(self.config_path, self.root/'context')

    def test_interrupted_initialization_can_reattach_without_losing_progress(self):
        receipt=C.next_read(self.project,80)
        C.mutate(self.project,'ack-read',receipt=receipt['receipt'],note='Existing saved read before simulated missing config attachment.')
        state=(self.project.parent/'state.json').read_bytes()
        cfg=C.read_json(self.config_path);cfg.pop('contextProject');self.config_path.write_text(json.dumps(cfg))
        self.assertEqual(C.initialize(self.config_path,self.project.parent),self.project)
        self.assertEqual((self.project.parent/'state.json').read_bytes(),state)
        self.assertEqual(C.next_read(self.project,80)['passages'][0]['start'],80)

    def test_interruption_replays_exact_bounded_range_without_advancing(self):
        first = C.next_read(self.project, 80)
        again = C.next_read(self.project, 80)
        self.assertEqual(first, again)
        self.assertLessEqual(first['characters'], 80)
        self.assertEqual(C.audit(self.project)['readPages'], 0)
        C.mutate(self.project, 'ack-read', receipt=first['receipt'], note='Actually read the first range.')
        next_chunk = C.next_read(self.project, 80)
        self.assertEqual(next_chunk['passages'][0]['start'], 80)
        C.mutate(self.project, 'ack-read', receipt=first['receipt'], note='Retry of saved acknowledgment.')
        self.assertEqual(C.next_read(self.project, 80), next_chunk)

    def test_overlapping_receipt_cannot_skip_a_range(self):
        small = C.next_read(self.project, 64)
        large = C.next_read(self.project, 150)
        C.mutate(self.project, 'ack-read', receipt=small['receipt'], note='Read shorter packet after host truncation.')
        with self.assertRaisesRegex(ValueError, 'Stale/overlapping'):
            C.mutate(self.project, 'ack-read', receipt=large['receipt'], note='Would overlap already acknowledged text.')

    def test_all_offsets_cover_source_exactly_after_restarts(self):
        self.read_all()
        state = C.read_json(self.project.parent/'state.json')
        text = (self.kb/'full_text.txt').read_text()
        spans = [span for receipt in state['receipts'].values() if receipt['acknowledged'] for span in receipt['spans']]
        spans.sort(key=lambda s:s['start'])
        self.assertEqual(''.join(text[s['start']:s['end']] for s in spans), text)
        self.assertEqual(C.audit(self.project)['readPages'], 1)
        self.assertEqual(C.audit(self.project)['status'], 'incomplete')

    def test_blank_source_requires_acknowledgment(self):
        # The separate corpus has no text, but an issued receipt still isn't a read acknowledgment.
        other = self.root/'blank'; other.mkdir()
        config = copy.deepcopy(self.cfg)
        kb = self.root/'blank-kb'; import shutil; shutil.copytree(self.kb, kb)
        (kb/'full_text.txt').write_text('')
        rows=C.read_json(kb/'source_map.json'); rows[0].update(start_char=0,end_char=0,content_sha256=hashlib.sha256(b'').hexdigest())
        (kb/'source_map.json').write_text(json.dumps(rows));config['knowledgeBase']=str(kb)
        path=other/'config.json';path.write_text(json.dumps(config));project=C.initialize(path,other/'context')
        receipt=C.next_read(project)
        self.assertEqual(C.audit(project)['readPages'],0)
        C.mutate(project,'ack-read',receipt=receipt['receipt'],note='Confirmed empty extracted text; visual status is checked separately.')
        self.assertEqual(C.audit(project)['readPages'],1)

    def test_completion_needs_ordered_explicit_reviews(self):
        with self.assertRaisesRegex(ValueError, 'remain'):
            C.mutate(self.project, 'review-book', note='Must fail while unread.')
        self.read_all()
        C.mutate(self.project, 'checkpoint', chapter='chapter-1', note='Saved.')
        with self.assertRaisesRegex(ValueError, 'precede'):
            C.mutate(self.project, 'review-chapter', chapter='chapter-1', phase='content', note='Out of order.')
        self.review_chapter()
        self.assertEqual(C.audit(self.project)['status'],'incomplete')
        C.mutate(self.project,'review-book',note='Checked all source, independent ideas, conditions, examples and the absence of figures in this synthetic source.')
        self.assertEqual(C.audit(self.project,True)['status'],'complete-with-recorded-review')

    def test_record_edit_invalidates_review_but_keeps_source_progress(self):
        self.finish()
        p=self.kb/'unit-records/u01.json';r=C.read_json(p);r['unit']['title']='Changed explanation';p.write_text(json.dumps(r))
        result=C.audit(self.project)
        self.assertEqual(result['readPages'],1)
        self.assertFalse(result['chapters'][0]['complete'])
        self.assertFalse(result['globalReviewCurrent'])
        self.review_chapter()
        self.assertFalse(C.audit(self.project)['globalReviewCurrent'])

    def test_outline_changes_invalidate_affected_chapter(self):
        self.finish()
        s=C.read_json(self.f.structure_path);s['originalStructure'][0]['title']='Revised original heading';self.f.structure_path.write_text(json.dumps(s))
        self.assertFalse(C.audit(self.project)['chapters'][0]['complete'])

    def test_source_changes_stop_reuse(self):
        self.read_all()
        p=self.kb/'full_text.txt';p.write_text(p.read_text()+'new')
        with self.assertRaisesRegex(ValueError,'corpus changed'):
            C.packet(self.project)

    def test_visual_changes_need_fresh_disposition(self):
        self.finish()
        folder=self.kb/'visual';folder.mkdir();p=folder/'qc-physical-pdf-1.png';p.write_bytes(b'synthetic-visual')
        self.assertEqual(C.audit(self.project)['visualPending'],[p.name])
        C.mutate(self.project,'review-visual',asset=p.name,disposition='reviewed',note='Inspected synthetic visual with its page locator.')
        C.mutate(self.project,'review-book',note='Global recheck with the newly registered visual.')
        self.assertTrue(C.audit(self.project)['globalReviewCurrent'])
        p.write_bytes(b'changed-visual')
        self.assertEqual(C.audit(self.project)['visualPending'],[p.name])

    def test_packet_is_compact_and_has_no_full_source_or_base64(self):
        packet=json.dumps(C.packet(self.project),ensure_ascii=False)
        self.assertLess(len(packet),5000)
        self.assertNotIn(self.f.raw,packet)
        self.assertNotIn('data:image',packet)

    def test_public_preparation_rejects_incomplete_context(self):
        cfg=P.load_config(self.config_path)
        with self.assertRaisesRegex(ValueError,'completeness pending'):
            P.prepare(cfg)
        self.assertFalse(cfg['publicDir'].exists())

    def test_ready_context_requires_rebuilding_changed_delivery(self):
        self.finish();cfg=P.load_config(self.config_path)
        P.build(cfg)
        self.assertEqual(P.require_context_complete(cfg),'complete-with-recorded-review')
        s=C.read_json(self.f.structure_path);s['authorThesis']='Different structure explanation';self.f.structure_path.write_text(json.dumps(s))
        C.mutate(self.project,'review-book',note='Reread globally after changing thesis.')
        with self.assertRaisesRegex(ValueError,'Rebuild'):
            P.require_context_complete(cfg)

    def test_legacy_is_not_retroactively_certified(self):
        self.assertEqual(P.require_context_complete({}),'legacy-not-certified')
        with self.assertRaisesRegex(ValueError,'Initialize/attach'):
            P.require_context_complete(dict(requireBookContext=True))


if __name__=='__main__':unittest.main()
