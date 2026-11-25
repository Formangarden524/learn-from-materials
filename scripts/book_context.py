#!/usr/bin/env python3
"""Bounded, source-first book handoffs. Receipts/checkpoints are not semantic proof."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from pipeline_state import locked, now
from workflow_io import read_json, json_text, write_changed, sha_file

SCHEMA = 'learn-from-materials/book-context-v1'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def note(value):
    need(isinstance(value, str) and bool(value.strip()), 'An actual reading/review note is required')
    need(len(value) <= 4000, 'Keep notes concise (at most 4000 characters)')
    return value.strip()


def resolve(base, value):
    p = Path(value).expanduser()
    return (base / p).resolve() if not p.is_absolute() else p.resolve()


def inputs(config_path):
    path = Path(config_path).resolve()
    cfg = read_json(path)
    need(cfg.get('schemaVersion') == 'learn-from-materials/book-pipeline-v1', 'Expected book pipeline configuration')
    kb = resolve(path.parent, cfg['knowledgeBase'])
    structure_path = resolve(path.parent, cfg['structure'])
    structure = read_json(structure_path)
    mapping = read_json(kb / 'source_map.json')
    raw = (kb / 'full_text.txt').read_text(encoding='utf-8')
    need(mapping and all(type(s.get('pdf_page')) is int for s in mapping), 'Page-mapped source required')
    need(len({s['source_id'] for s in mapping}) == len(mapping), 'Duplicate source IDs')
    passages = {}
    for row in mapping:
        text = raw[row['start_char']:row['end_char']]
        need(hashlib.sha256(text.encode()).hexdigest() == row['content_sha256'], 'Source slice changed: ' + row['source_id'])
        passages[row['source_id']] = text
    manifest = read_json(kb / 'source_manifest.json')
    originals = manifest.get('sources', [])
    need(len(originals) == 1 and originals[0].get('sha256'), 'One source book per context')
    if cfg.get('sourcePdf'):
        need(sha_file(resolve(path.parent, cfg['sourcePdf'])) == originals[0]['sha256'], 'Original book changed; re-extract and explicitly migrate, do not reuse old read receipts')
    fingerprint = digest({'original': originals[0]['sha256'], 'raw': sha_file(kb / 'full_text.txt'), 'mapping': mapping})
    chapters = []
    for i, row in enumerate(structure.get('originalStructure', [])):
        key = 'chapter-' + str(row['chapterNumber'])
        chapters.append((key, row))
    for i, row in enumerate(structure.get('attachments', [])):
        chapters.append(('attachment-' + str(row.get('id', i)), row))
    need(chapters and len({k for k, r in chapters}) == len(chapters), 'Unique original chapters required')
    for key, row in chapters:
        need(isinstance(row.get('pageStart'), int) and isinstance(row.get('pageEnd'), int) and row['pageStart'] <= row['pageEnd'], 'Explicit page bounds required: ' + key)
    visuals = {}
    for p in sorted((kb / 'visual').glob('*')):
        if not p.is_file():
            continue
        match = re.match(r'(?:qc-physical-pdf-|pdf-)(\d+)(?:\.|-image-)', p.name)
        need(match, 'Visual asset needs page locator: ' + p.name)
        visuals[p.name] = {'page': int(match[1]), 'sha256': sha_file(p)}
    return dict(config=path, cfg=cfg, kb=kb, structure=structure, mapping=mapping,
                passages=passages, fingerprint=fingerprint, chapters=chapters, visuals=visuals)


def initialize(config_path, directory):
    src = inputs(config_path)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    project = directory / 'project.json'
    with locked(directory / '.context.lock'):
        existing = src['cfg'].get('contextProject')
        need(not existing or resolve(src['config'].parent, existing) == project, 'Configuration is already attached to another book context')
        if project.exists():
            # Recovery if interruption happened after writing context but before attaching config.
            need(not existing, 'Book context already exists; use packet to resume')
            previous = read_json(project)
            need(previous.get('schemaVersion') == SCHEMA and previous.get('config') == str(src['config']) and
                 previous.get('sourceFingerprint') == src['fingerprint'], 'Existing context belongs to different inputs')
            saved = read_json(directory / 'state.json')
            need(saved.get('schemaVersion') == SCHEMA, 'Invalid retained state')
            cfg = src['cfg']; cfg['contextProject'] = str(project)
            write_changed(src['config'], json_text(cfg))
            save_handoff(project, previous, saved, src)
            return project
        body = dict(schemaVersion=SCHEMA, bookId='book-' + src['fingerprint'][:16],
                    title=src['structure'].get('bookTitle', ''), config=str(src['config']),
                    sourceFingerprint=src['fingerprint'], createdAt=now())
        state = dict(schemaVersion=SCHEMA, offsets={}, receipts={}, chapters={}, visuals={}, globalReview=None)
        if (directory / 'state.json').exists():
            need(read_json(directory / 'state.json') == state, 'Existing nonempty context state must not be overwritten')
        write_changed(directory / 'state.json', json_text(state))
        write_changed(project, json_text(body))
        cfg = src['cfg']; cfg['contextProject'] = str(project)
        write_changed(src['config'], json_text(cfg))
        save_handoff(project, body, state, src)
    return project


def load(project):
    path = Path(project).resolve()
    body = read_json(path)
    need(body.get('schemaVersion') == SCHEMA, 'Expected book context')
    state = read_json(path.parent / 'state.json')
    need(state.get('schemaVersion') == SCHEMA, 'Invalid context state')
    src = inputs(body['config'])
    need(src['cfg'].get('contextProject') and resolve(src['config'].parent, src['cfg']['contextProject']) == path, 'Book context/configuration binding differs')
    need(src['fingerprint'] == body['sourceFingerprint'], 'Source corpus changed; retained progress is stale. Re-extract and explicitly migrate before continuing')
    for sid, offset in state['offsets'].items():
        need(sid in src['passages'] and type(offset) is int and 0 <= offset <= len(src['passages'][sid]), 'Invalid saved read offset')
    return path, body, state, src


def read_ids(state, src):
    return {sid for sid, text in src['passages'].items() if sid in state['offsets'] and state['offsets'][sid] == len(text)}


def chapter_signature(row, src):
    ids = row.get('unitIds', [])
    need(ids and len(ids) == len(set(ids)), 'Chapter needs explicit unique unit IDs')
    result = {}
    for uid in ids:
        need(isinstance(uid, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', uid) and uid not in ('.', '..'), 'Invalid unit ID')
        p = src['kb'] / 'unit-records' / (uid + '.json')
        r = read_json(p)
        need(r.get('schemaVersion') in ('learn-from-materials/book-unit-v1', 'learn-from-materials/unit-record-v2'), 'Unsupported unit record')
        need(r['unit']['id'] == uid, 'Canonical unit ID mismatch')
        leaves = set()
        def walk(value):
            if isinstance(value, dict):
                if 'id' in value and 'text' in value:
                    leaves.add(value['id'])
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(r['unit'])
        mapped = set()
        need(r.get('claims'), 'Canonical unit needs source-mapped claims')
        for claim in r['claims']:
            need(claim.get('sourceIds') and set(claim['sourceIds']) <= set(src['passages']), 'Unknown/missing source in claim')
            need(set(claim.get('contentIds', [])) <= leaves, 'Claim points to unknown content')
            mapped.update(claim.get('contentIds', []))
        need(leaves and leaves <= mapped, 'Displayed content is not fully source-mapped')
        result[uid] = sha_file(p)
    return digest({'outlineRow': row, 'records': result}), result


def audit_data(body, state, src):
    read = read_ids(state, src)
    chapters, expected = [], []
    signatures = {}
    for key, row in src['chapters']:
        expected.extend(row.get('unitIds', []))
        saved = state['chapters'].get(key, {})
        try:
            signature, records = chapter_signature(row, src)
            signatures[key] = signature
            fresh = saved.get('signature') == signature
            pages = [s['source_id'] for s in src['mapping'] if row['pageStart'] <= s['pdf_page'] <= row['pageEnd']]
            need(pages, 'Chapter has no mapped source pages')
            done = fresh and all(s in read for s in pages) and all(saved.get('reviews', {}).get(p, {}).get('signature') == signature for p in ('source', 'content'))
            reason = 'reviewed' if done else ('not-checkpointed-or-changed' if not fresh else 'reading-or-two-pass-review-pending')
        except (ValueError, OSError, KeyError, TypeError) as e:
            done = False; reason = str(e)
        chapters.append(dict(id=key, title=row.get('title', ''), complete=bool(done), reason=reason))
    actual = {p.stem for p in (src['kb'] / 'unit-records').glob('*.json')}
    mapping_ok = bool(expected) and len(expected) == len(set(expected)) and set(expected) == actual
    visual_pending = [name for name, v in src['visuals'].items() if state['visuals'].get(name, {}).get('sha256') != v['sha256']]
    signature = digest(dict(source=src['fingerprint'], outline=src['structure'], offsets=state['offsets'],
                            chapters=signatures, visuals=src['visuals'], visualReviews=state['visuals']))
    ready = len(read) == len(src['passages']) and all(c['complete'] for c in chapters) and mapping_ok and not visual_pending
    global_review = state.get('globalReview') or {}
    complete = ready and global_review.get('signature') == signature
    return dict(status='complete-with-recorded-review' if complete else 'incomplete', bookId=body['bookId'],
                readPages=len(read), sourcePages=len(src['mapping']), chapters=chapters,
                canonicalMappingComplete=mapping_ok, visualPending=visual_pending,
                globalReviewCurrent=complete, readyForGlobalReview=ready, signature=signature,
                semanticProof='Execution receipts and reviewer declarations, not automatic proof of semantic completeness')


def audit(project, require_complete=False):
    path = Path(project).resolve()
    with locked(path.parent / '.context.lock'):
        _, body, state, src = load(path)
        result = audit_data(body, state, src)
        write_changed(path.parent / 'completeness.json', json_text(result))
        if require_complete:
            need(result['status'] == 'complete-with-recorded-review', 'Full-book completeness pending; inspect context completeness.json and resume packet')
        return result


def save_handoff(path, body, state, src):
    read = read_ids(state, src)
    pending = [r for r in src['mapping'] if r['source_id'] not in read]
    cmd = [sys.executable, str(Path(__file__).resolve()), 'packet', str(path)]
    text = f"# {body['title']}\n\nBook: {body['bookId']}\nProject: {path}\nRead: {len(read)}/{len(src['mapping'])} source pages.\n\n"
    text += 'Use a separate conversation for this book. This file does not create a chat, clear host context, or certify reading.\n\n'
    text += 'Resume command (argument array):\n```json\n' + json.dumps(cmd, ensure_ascii=False) + '\n```\n'
    text += '\nNext source: ' + (pending[0]['source_id'] if pending else 'all source text acknowledged; check chapter/visual/global review') + '\n'
    text += '\nCanonical content stays in the configured knowledge base. Read the packet, not the whole HTML/JSON with embedded images.\n'
    write_changed(path.parent / 'HANDOFF.md', text)


def packet(project):
    path = Path(project).resolve()
    with locked(path.parent / '.context.lock'):
        _, body, state, src = load(path)
        result = audit_data(body, state, src)
        pending = [r for r in src['mapping'] if r['source_id'] not in read_ids(state, src)]
        save_handoff(path, body, state, src)
        return dict(bookId=body['bookId'], title=body['title'], project=str(path), scope='full-book',
                    status=result['status'], progress=f"{result['readPages']}/{result['sourcePages']} source pages",
                    chapterCount=len(result['chapters']), chaptersPending=sum(not c['complete'] for c in result['chapters']),
                    nextChapters=[c for c in result['chapters'] if not c['complete']][:5],
                    nextSource={k: pending[0][k] for k in ('source_id', 'pdf_page')} if pending else None,
                    visualPendingCount=len(result['visualPending']), visualNext=result['visualPending'][:5],
                    globalReviewCurrent=result['globalReviewCurrent'],
                    unacknowledgedReceipts=[k for k, v in state['receipts'].items() if not v.get('acknowledged')][:5],
                    canonicalPaths=dict(knowledgeBase=str(src['kb']), structure=str(resolve(src['config'].parent, src['cfg']['structure']))),
                    nextReadCommand=['book_context.py', 'read-next', str(path), '--chars', '12000'],
                    note='Only source access/review declarations are recorded. Independent content, cases, conditions and figures still require actual reading and review; no fixed card quota.')


def next_read(project, chars=12000):
    need(type(chars) is int and 64 <= chars <= 40000, 'Chunk size must be between 64 and 40000 characters')
    path = Path(project).resolve()
    with locked(path.parent / '.context.lock'):
        _, body, state, src = load(path)
        spans, remaining = [], chars
        read = read_ids(state, src)
        for row in src['mapping']:
            sid = row['source_id']
            if sid in read: continue
            start = state['offsets'].get(sid, 0)
            end = min(len(src['passages'][sid]), start + remaining)
            spans.append(dict(sourceId=sid, page=row['pdf_page'], start=start, end=end))
            remaining -= end - start
            if remaining == 0: break
        if not spans:
            return dict(status='source-text-acknowledged', next='Review chapters, visuals and whole-book completeness; do not auto-complete')
        receipt = digest({'book': body['bookId'], 'spans': spans})[:24]
        state['receipts'].setdefault(receipt, dict(spans=spans, issuedAt=now(), acknowledged=False))
        write_changed(path.parent / 'state.json', json_text(state))
        return dict(bookId=body['bookId'], receipt=receipt, characters=chars-remaining,
                    status='issued-not-read', warning='Read the whole returned text; this command has not advanced progress. If the host truncates output, reissue a smaller packet before acknowledgment.',
                    passages=[dict(s, text=src['passages'][s['sourceId']][s['start']:s['end']]) for s in spans])


def mutate(project, action, **values):
    path = Path(project).resolve()
    with locked(path.parent / '.context.lock'):
        _, body, state, src = load(path)
        text_note = note(values.get('note'))
        if action == 'ack-read':
            receipt = state['receipts'].get(values['receipt'])
            need(receipt is not None, 'Unknown receipt for this book')
            if not receipt.get('acknowledged'):
                for span in receipt['spans']:
                    need(state['offsets'].get(span['sourceId'], 0) == span['start'], 'Stale/overlapping read receipt; issue read-next again')
                for span in receipt['spans']: state['offsets'][span['sourceId']] = span['end']
                receipt.update(acknowledged=True, note=text_note, at=now())
        elif action in ('checkpoint', 'review-chapter'):
            key = values['chapter']; rows = dict(src['chapters'])
            need(key in rows, 'Unknown chapter in this book')
            row = rows[key]; signature, records = chapter_signature(row, src)
            saved = state['chapters'].get(key, {})
            if action == 'checkpoint':
                if saved.get('signature') != signature:
                    saved = dict(signature=signature, records=records, reviews={})
                saved.update(note=text_note, at=now()); state['chapters'][key] = saved
            else:
                need(saved.get('signature') == signature, 'Changed/uncheckpointed chapter; checkpoint actual records before review')
                need(all(r['source_id'] in read_ids(state, src) for r in src['mapping'] if row['pageStart'] <= r['pdf_page'] <= row['pageEnd']), 'Chapter source reading is incomplete')
                phase = values['phase']
                if phase == 'content': need(saved['reviews'].get('source', {}).get('signature') == signature, 'Source-first reread/review must precede completeness review')
                saved['reviews'][phase] = dict(signature=signature, note=text_note, at=now())
        elif action == 'review-visual':
            name = values['asset']; need(name in src['visuals'], 'Unknown page-located visual asset')
            state['visuals'][name] = dict(sha256=src['visuals'][name]['sha256'], disposition=values['disposition'], note=text_note, at=now())
        elif action == 'review-book':
            report = audit_data(body, state, src)
            need(report['readyForGlobalReview'], 'Unread pages, missing/changed chapters, visuals or mapping remain')
            state['globalReview'] = dict(signature=report['signature'], note=text_note, at=now(),
                                        scope='Reviewer confirms all independent content/cases/conditions and key figures; declaration is not generated by a mechanical check')
        else:
            raise ValueError('Unknown mutation')
        write_changed(path.parent / 'state.json', json_text(state))
        save_handoff(path, body, state, src)
        return dict(status='saved', action=action, bookId=body['bookId'], semanticApproval='not-granted-by-script')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('config', type=Path); init.add_argument('--output', required=True, type=Path)
    for command in ('packet', 'read-next', 'ack-read', 'checkpoint', 'review-chapter', 'review-visual', 'review-book', 'audit'):
        p = sub.add_parser(command); p.add_argument('project', type=Path)
        if command == 'read-next': p.add_argument('--chars', type=int, default=12000)
        if command == 'ack-read': p.add_argument('--receipt', required=True)
        if command in ('checkpoint', 'review-chapter'): p.add_argument('--chapter', required=True)
        if command == 'review-chapter': p.add_argument('--phase', choices=('source', 'content'), required=True)
        if command == 'review-visual':
            p.add_argument('--asset', required=True); p.add_argument('--disposition', choices=('reviewed', 'not-content'), required=True)
        if command == 'audit': p.add_argument('--require-complete', action='store_true')
        if command not in ('packet', 'read-next', 'audit'): p.add_argument('--note', required=True)
    args = vars(parser.parse_args()); command = args.pop('command')
    if command == 'init': result = dict(project=str(initialize(args['config'], args['output'])), status='initialized-unread')
    elif command == 'packet': result = packet(args['project'])
    elif command == 'read-next': result = next_read(args['project'], args['chars'])
    elif command == 'audit': result = audit(args['project'], args['require_complete'])
    else:
        project = args.pop('project'); result = mutate(project, command, **args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit('Book context stopped: ' + str(error))
