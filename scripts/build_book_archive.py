#!/usr/bin/env python3
"""Reuse canonical book records as an author-led archive, webpage and Wiki handoff."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import base64
import mimetypes
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cover_assets import load_cover
import re
import shutil
import time


SCHEMA = 'learn-from-materials/author-book-v1'
BUILD_SCHEMA = 'learn-from-materials/author-book-build-v1'
MANAGED = ['书籍档案', '阅读网页.html', '构建报告.json']


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def text(value):
    return value.get('text', '') if isinstance(value, dict) else str(value)


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ordered_parts(structure):
    parts = [*structure.get('originalStructure', []), *structure.get('attachments', [])]
    return sorted(parts, key=lambda row: row['pageStart'] if isinstance(row.get('pageStart'), (int, float)) else float('inf'))


def structure_review(structure):
    status = structure.get('structureStatus')
    evidence = structure.get('confirmationEvidence')
    explicit_evidence = ((isinstance(evidence, str) and bool(evidence.strip())) or
                         (isinstance(evidence, dict) and any(isinstance(value, str) and value.strip() for value in evidence.values())))
    if status == 'confirmed-by-user' and explicit_evidence:
        return 'confirmed-by-user'
    if status in ('needs-revision', 'rejected-by-user'):
        return status
    return 'pending-user-review'


def structure_label(book):
    return {'confirmed-by-user': '用户已确认', 'needs-revision': '待修改',
            'rejected-by-user': '用户未通过'}.get(book['meta']['structureReview'], '待用户确认')


def validate_structure(structure, unit_ids):
    for key in ('centralQuestion', 'authorThesis', 'representativeScope'):
        need(isinstance(structure.get(key), str) and structure[key].strip(), 'Missing structure.' + key)
    need(structure.get('representativeUnitId') in unit_ids, 'Representative unit must reference a real unit')
    chapters = structure.get('originalStructure')
    need(isinstance(chapters, list) and chapters, 'Original chapter structure must not be empty')
    chapter_ids = [row.get('chapterNumber') for row in chapters]
    need(all(type(value) is int and value > 0 for value in chapter_ids), 'Original chapters need positive integer chapterNumber')
    need(len(chapter_ids) == len(set(chapter_ids)), 'Duplicate original chapter number')
    need(all(isinstance(row.get('title'), str) and row['title'].strip() for row in chapters), 'Original chapter title is missing')
    for chapter in chapters:
        for field in ('readingQuestion', 'bridge', 'originalSectionLabel', 'originalPart'):
            if field in chapter:
                need(isinstance(chapter[field], str) and chapter[field].strip(), 'Invalid chapter.' + field)
        if 'concepts' in chapter:
            value = chapter['concepts']
            need((isinstance(value, str) and value.strip()) or
                 (isinstance(value, list) and value and all(isinstance(x, str) and x.strip() for x in value)), 'Invalid chapter.concepts')
        need(not any(field in chapter for field in ('concepts', 'bridge')) or chapter.get('readingQuestion'), 'Chapter route needs readingQuestion')
    groups = structure.get('groups')
    need(isinstance(groups, list) and groups, 'Reading groups must not be empty')
    group_ids = [row.get('id') for row in groups]
    need(all(isinstance(value, str) and value.strip() for value in group_ids), 'Reading groups need IDs')
    need(len(group_ids) == len(set(group_ids)), 'Duplicate reading group ID')
    for group in groups:
        for key in ('title', 'question', 'summary', 'relation'):
            need(isinstance(group.get(key), str) and group[key].strip(), 'Missing group.' + key)
        numbers = group.get('chapterNumbers')
        need(isinstance(numbers, list) and numbers and all(number in chapter_ids for number in numbers), 'Reading group references an unknown chapter')
        need(len(numbers) == len(set(numbers)), 'Duplicate chapter within a reading group')


def collect(kb, structure, source_pdf=None, title=None, author=None):
    """Read existing material only. No model authoring or semantic approval occurs."""
    kb = Path(kb).resolve()
    raw = (kb / 'full_text.txt').read_text(encoding='utf-8')
    source_rows = read(kb / 'source_map.json')
    manifest = read(kb / 'source_manifest.json')
    records = [read(path) for path in sorted((kb / 'unit-records').glob('*.json'))]
    need(records, 'No canonical unit-records found')
    need(all(row.get('schemaVersion') in ('learn-from-materials/unit-record-v2', 'learn-from-materials/book-unit-v1') for row in records), 'Expected existing unit-record-v2 or lightweight book-unit-v1 records')
    unit_ids = [row['unit']['id'] for row in records]
    need(len(unit_ids) == len(set(unit_ids)), 'Duplicate unit IDs')
    need(source_rows and all(type(row.get('pdf_page')) is int and row['pdf_page'] > 0 for row in source_rows), 'Author-book assembly currently requires PDF page mappings; use the existing quick/systematic workflow for non-PDF sources')
    validate_structure(structure, unit_ids)
    source_ids = [row['source_id'] for row in source_rows]
    need(len(source_ids) == len(set(source_ids)), 'Duplicate source IDs')
    sources = []
    by_source = {}
    for row in source_rows:
        passage = raw[row['start_char']:row['end_char']]
        need(hashlib.sha256(passage.encode('utf-8')).hexdigest() == row['content_sha256'], 'Source slice changed: ' + row['source_id'])
        page = row.get('pdf_page')
        images = []
        if page is not None:
            for file in sorted((kb / 'visual').glob('*')):
                match = re.match(r'pdf-(\d+)-image-', file.name)
                qc_match = re.match(r'qc-physical-pdf-(\d+)\.', file.name)
                if (match and int(match[1]) == page) or (qc_match and int(qc_match[1]) == page):
                    images.append('书籍档案/knowledge/visual/' + file.name)
        source = {'id': row['source_id'], 'page': page, 'file': row['source_file'],
                  'text': passage, 'visualPaths': images, 'contentSha256': row['content_sha256']}
        sources.append(source)
        by_source[source['id']] = source
    claim_ids = set()
    for record in records:
        for source in record['sources']:
            need(source['sourceId'] in by_source, 'Unknown unit source: ' + source['sourceId'])
        leaves = set()
        def collect_leaves(value):
            if isinstance(value, dict):
                if 'id' in value and 'text' in value:
                    leaves.add(value['id'])
                for child in value.values():
                    collect_leaves(child)
            elif isinstance(value, list):
                for child in value:
                    collect_leaves(child)
        collect_leaves(record['unit'])
        mapped = set()
        for claim in record['claims']:
            need(claim['id'] not in claim_ids, 'Duplicate claim ID: ' + claim['id'])
            claim_ids.add(claim['id'])
            need(claim.get('sourceIds') and all(sid in by_source for sid in claim['sourceIds']), 'Unknown or missing claim source: ' + claim['id'])
            need(set(claim.get('contentIds', [])) <= leaves, 'Claim points to an unknown display ID: ' + claim['id'])
            mapped.update(claim.get('contentIds', []))
        need(leaves <= mapped, 'Displayed content lacks source mapping: ' + record['unit']['id'])
    structure = copy.deepcopy(structure)
    memberships = []
    for group in ordered_parts(structure):
        need(isinstance(group.get('unitIds'), list), 'Each original chapter/attachment needs explicit unitIds')
        memberships.extend(group['unitIds'])
    need(set(memberships) == set(unit_ids), 'Original chapter/attachment mapping must cover exactly the reused units')
    need(len(memberships) == len(set(memberships)), 'A unit belongs to more than one chapter/attachment')
    by_unit = {record['unit']['id']: record for record in records}
    records = [by_unit[uid] for uid in memberships]
    unit_ids = memberships
    structure_quote_count = 0
    def check_structure(value):
        nonlocal structure_quote_count
        if isinstance(value, dict):
            if value.get('sourceId') and value.get('quote'):
                sid = value['sourceId']
                need(sid in by_source and value['quote'] in by_source[sid]['text'], 'Structure quotation differs from original: ' + sid)
                structure_quote_count += 1
            for child in value.values():
                check_structure(child)
        elif isinstance(value, list):
            for child in value:
                check_structure(child)
    check_structure(structure)
    review_path = kb / 'content-review.json'
    inherited_reviews = read(review_path) if review_path.exists() else {}
    reviews = {r['unitId']: r for r in inherited_reviews.get('unitReviews', [])}
    matched, missing = [], []
    for record in records:
        uid = record['unit']['id']
        if uid not in reviews:
            missing.append(uid)
        else:
            need(reviews[uid].get('reviewedInputs', {}).get('record') == digest(record), 'Inherited record review is stale: ' + uid)
            matched.append(uid)
    originals = manifest['sources']
    need(originals and originals[0].get('sha256'), 'Source manifest needs stable original file fingerprint')
    first = originals[0]
    source_pdf = Path(source_pdf).expanduser().resolve() if source_pdf else None
    if source_pdf is None:
        candidate = Path.home() / 'Downloads' / first['source_file']
        if candidate.is_file():
            source_pdf = candidate
    pdf_check = 'not-located'
    if source_pdf:
        need(source_pdf.is_file(), 'Original PDF not found')
        need(sha(source_pdf) == first['sha256'], 'Original PDF changed; do not reuse unchanged-review claims')
        pdf_check = 'matched'
    title = title or structure.get('bookTitle')
    author = author or structure.get('author')
    need(title and author, 'Declare original bookTitle and author, or provide --title/--author')
    fingerprint_paths = ['source_manifest.json', 'source_map.json', 'source-heading-index.json', 'full_text.txt']
    fingerprint_paths += ['unit-records/' + uid + '.json' for uid in unit_ids]
    if review_path.exists():
        fingerprint_paths.append('content-review.json')
    fingerprints = {name: sha(kb / name) for name in fingerprint_paths}
    book = {'schemaVersion': SCHEMA,
            'meta': {'bookId': 'book-' + first['sha256'][:16], 'title': title, 'author': author,
                     'unitCount': len(records), 'pageCount': max((s['page'] or 0) for s in sources),
                     'sourcePdf': str(source_pdf) if source_pdf else '',
                     'note': '档案和网页由所提供的单书记录生成；作者原章与编辑归纳分层，实际阅读和核验范围以内容记录及来源说明为准。',
                     'structureReview': structure_review(structure), 'originalSha256': first['sha256']},
            'structure': structure, 'units': records, 'sources': sources,
            'provenance': {'sourceKnowledgeBase': str(kb), 'inputFingerprints': fingerprints,
                           'structureSha256': digest(structure), 'reusedReviewStatus': 'inherited' if not missing else 'partial-or-missing',
                           'newSemanticReview': False, 'originalPdfFingerprint': pdf_check,
                           'sourceSliceHashes': {'matched': len(sources), 'total': len(sources)},
                           'recordReviewDigests': {'matched': len(matched), 'missingUnitIds': missing},
                           'structureQuotesChecked': structure_quote_count,
                           'mappingCheck': 'each-unit-exactly-one-original-chapter-or-attachment',
                           'reviewNote': '历史复核原样保留。机械一致性不等于本轮语义复核或用户已确认新结构。'}}
    return book


def unit_content_lines(record):
    unit = record['unit']
    lines = ['### 核心思想', '', text(unit['core']), '', '### 要点', '']
    lines += ['- ' + text(value) for value in unit.get('takeaways', [])]
    for conclusion in unit.get('conclusions', []):
        lines += ['', '### ' + conclusion['title'], '', text(conclusion['summary']), '']
        lines += ['- ' + text(value) for value in conclusion.get('points', [])]
        lines += ['', conclusion.get('source', unit['source'])]
    if record.get('frameworks'):
        lines += ['', '### 本书框架及机制（沿用拆解归纳，非均作者命名）', '']
        for row in record['frameworks']:
            lines += ['- **' + row['name'] + '**：' + row.get('oneLine', ''),
                      '  ' + row.get('when', ''), '  ' + row.get('source', '')]
    if record.get('glossary'):
        lines += ['', '### 本书概念', '']
        for row in record['glossary']:
            lines += ['- **' + row['term'] + '**：' + row.get('definition', ''),
                      '  ' + row.get('context', ''), '  ' + row.get('source', '')]
    if record.get('decisionRules'):
        lines += ['', '### 原书判断与做法的记录', '']
        for row in record['decisionRules']:
            lines += ['- 当' + row['when'] + '，' + row['do'] + '。因为' + row['because'] + '。', '  ' + row['source']]
    headings = {'mentalModels': '结构与关系', 'antiPatterns': '原书讨论的反例与错误做法',
                'workedExamples': '原书案例与比喻', 'connections': '与前后文的联系'}
    for key, label in headings.items():
        if record.get('sections', {}).get(key):
            lines += ['', '### ' + label, '']
            lines += ['- ' + text(value) for value in record['sections'][key]]
    return lines


def archive_markdown(book):
    lines = ['# ' + book['meta']['title'] + '｜单书内容档案', '',
             '作者：' + book['meta']['author'], '', book['meta']['note'], '',
             '主线状态：' + structure_label(book) + '。所有正文从既有规范记录派生，完整原记录及证据留在knowledge目录。', '',
             '## 原书结构', '']
    for chapter in ordered_parts(book['structure']):
        lines += ['- ' + chapter['title'] + '：' + '、'.join(chapter['unitIds'])]
    for record in book['units']:
        unit = record['unit']; uid = unit['id']
        lines += ['', '## ' + unit['label'] + '｜' + unit['title'], '', unit['source'], '',
                  '[完整规范记录](knowledge/unit-records/' + uid + '.json) · [原派生单元](knowledge/units/' + uid + '.md)', '']
        lines += unit_content_lines(record)
    return '\n'.join(lines) + '\n'


def ensure_readable_exports(book, knowledge):
    """Create only absent projections; never rewrite original derived files."""
    created = []
    units_dir = knowledge / 'units'
    units_dir.mkdir(exist_ok=True)
    for record in book['units']:
        unit = record['unit']; uid = unit['id']
        path = units_dir / (uid + '.md')
        if path.exists():
            continue
        lines = ['# ' + unit['label'] + '｜' + unit['title'], '', unit['source'], '',
                 '[完整规范记录](../unit-records/' + uid + '.json)', '',
                 '由单份内容记录派生；不新增或升级语义审核状态。', '']
        path.write_text('\n'.join(lines + unit_content_lines(record)) + '\n', encoding='utf-8')
        created.append('units/' + uid + '.md')
    index = knowledge / 'INDEX.md'
    if not index.exists():
        by_unit = {row['unit']['id']: row['unit'] for row in book['units']}
        lines = ['# ' + book['meta']['title'] + '｜单书内容索引', '',
                 '主线状态：' + structure_label(book) + '。索引由内容记录派生，不新增语义审核状态。', '']
        for part in ordered_parts(book['structure']):
            lines += ['## ' + part['title'], '']
            lines += ['- [' + by_unit[uid]['title'] + '](units/' + uid + '.md)' for uid in part['unitIds']]
            lines.append('')
        index.write_text('\n'.join(lines), encoding='utf-8')
        created.append('INDEX.md')
    return created


def wiki_export(book):
    bid = book['meta']['bookId']; candidates = []; claims = []; units = []
    attribution_by_unit = {}
    for part in ordered_parts(book['structure']):
        context = part.get('attribution') or '本书正文叙述语境；具体引文、病例和转述的发言者以原记录及定位为准。'
        for uid in part['unitIds']:
            attribution_by_unit[uid] = context
    for record in book['units']:
        uid = record['unit']['id']; record_path = 'knowledge/unit-records/' + uid + '.json'
        attribution = attribution_by_unit[uid]
        units.append({'id': bid + '#' + uid, 'sourceUnitId': uid, 'title': record['unit']['title'],
                      'source': record['unit']['source'], 'originalRecord': record_path,
                      'bookAuthor': book['meta']['author'], 'unitAttribution': attribution,
                      'sourceIds': [s['sourceId'] for s in record['sources']]})
        for row in record['claims']:
            claims.append({'id': bid + '#' + row['id'], 'sourceClaimId': row['id'], 'unitId': bid + '#' + uid,
                           'text': row['text'], 'kind': row['kind'], 'source': row['source'],
                           'sourceIds': row['sourceIds'], 'contentIds': row['contentIds'],
                           'evidence': row['evidence'], 'originalRecord': record_path,
                           'bookAuthor': book['meta']['author'], 'unitAttribution': attribution,
                           'status': 'book-scoped-not-cross-book-merged'})
        for row in record.get('glossary', []):
            candidates.append({'id': bid + '#' + row['id'], 'sourceEntityId': row['id'], 'kind': 'concept-candidate',
                               'term': row['term'], 'definition': row['definition'], 'context': row.get('context', ''),
                               'source': row['source'], 'sourceUnitIds': row.get('units', [uid]),
                               'originalRecord': record_path, 'canonical': copy.deepcopy(row),
                               'bookAuthor': book['meta']['author'], 'unitAttribution': attribution,
                               'status': 'book-scoped-not-cross-book-merged'})
    return {'schemaVersion': 'learn-from-materials/book-wiki-export-v1', 'book': copy.deepcopy(book['meta']),
            'scope': 'single-book-only', 'pathBase': 'directory-containing-this-file',
            'wikiWritePerformed': False, 'crossBookMergePerformed': False,
            'units': units, 'claims': claims, 'conceptCandidates': candidates,
            'sources': [{'id': s['id'], 'page': s['page'], 'file': s['file'], 'contentSha256': s['contentSha256'],
                         'originalMap': 'knowledge/source_map.json'} for s in book['sources']],
            'contentArchive': 'book.json', 'evidenceAssetBase': 'knowledge/',
            'inheritedReview': 'knowledge/content-review.json' if 'content-review.json' in book['provenance']['inputFingerprints'] else None,
            'note': 'bookAuthor仅表示书籍署名，不等于每条引文的发言者。单元叙述语境取自原章或附属材料的归属说明；具体引文、病例和转述的实际身份保留在原记录与定位中。候选只供后续主题Wiki选择比较，不自动成为跨书共识或通用事实。'}


def build(args):
    mechanical_started = time.perf_counter()
    kb = args.knowledge_base.resolve(); output = args.output_dir.resolve()
    need(kb != output and kb not in output.parents and output not in kb.parents, 'Knowledge base and output must be separate, non-nested directories; choose a sibling delivery directory')
    template = Path(__file__).resolve().parents[1] / 'templates/author-book.html'
    need(template.is_file(), 'Author-book template not found')
    template_text = template.read_text(encoding='utf-8')
    need(template_text.count('__BOOK_DATA__') == 1, 'Template requires one __BOOK_DATA__ slot')
    book = collect(kb, read(args.structure), args.source_pdf, args.title, args.author)
    if args.representative_reading:
        preview = read(args.representative_reading)
        source_index = {row['id']: row for row in book['sources']}
        quotes = preview['quotes']
        for quote in quotes:
            sid = quote.get('sourceBlockId')
            need(sid in source_index and quote['text'] in source_index[sid]['text'], 'Representative quotation differs from original')
            if quote.get('context'):
                need(quote['context'] in source_index[sid]['text'], 'Representative context differs from original')
            if quote.get('page') is not None:
                need(quote['page'] == source_index[sid]['page'], 'Representative page mismatch')
        sections = preview.get('sections', preview.get('stages', []))
        need(sections, 'Representative reading has no content sections')
        quote_ids = {quote['id'] for quote in quotes}
        def check_rep_sources(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'sourceIds':
                        need(all(qid in quote_ids for qid in child), 'Unknown representative source reference')
                    else:
                        check_rep_sources(child)
            elif isinstance(value, list):
                for child in value:
                    check_rep_sources(child)
        check_rep_sources(sections)
        for section in sections:
            need(section.get('sourceIds'), 'Missing representative source reference')
        book['representativeReading'] = {'unitId': book['structure']['representativeUnitId'],
            'sectionHeading': preview.get('presentation', {}).get('sectionHeading', '沿原书结构展开'),
            'sections': copy.deepcopy(sections), 'quotes': copy.deepcopy(quotes),
            'note': '沿用已有样板讲解；不改写原规范单元，全部解释保留其原文入口。'}
        book['provenance']['representativeReadingSha256'] = sha(args.representative_reading)
    if getattr(args, 'cover_image', None):
        book['meta']['cover'] = load_cover(args.cover_image, book['meta']['title'], getattr(args, 'cover_page', None))
    elif getattr(args, 'cover_page', None):
        raise ValueError('--cover-page requires --cover-image')
    report_path = output / '构建报告.json'
    conflicts = [name for name in MANAGED if (output / name).exists()]
    if conflicts:
        need(args.force and report_path.is_file(), 'Output exists; use a fresh directory or --force for a previous tool build')
        old = read(report_path)
        need(old.get('schemaVersion') == BUILD_SCHEMA and old.get('managedPaths') == MANAGED, 'Cannot overwrite unowned output')
        old_hashes = old.get('managedFileHashes')
        need(isinstance(old_hashes, dict), 'Previous build has no per-file ownership map; choose a fresh output directory')
        current_files = set()
        for name in MANAGED:
            item = output / name
            if item.is_dir():
                current_files.update(file.relative_to(output).as_posix() for file in item.rglob('*') if file.is_file())
            elif item.is_file() and name != '构建报告.json':
                current_files.add(name)
        need(current_files <= set(old_hashes), 'Unowned files found in managed directories; preserve them before rebuilding')
        need(all(sha(output / rel) == old_hashes[rel] for rel in current_files), 'A generated file was manually changed; use a fresh output directory')
        for name in MANAGED:
            file = output / name
            if file.is_dir(): shutil.rmtree(file)
            elif file.exists(): file.unlink()
    output.mkdir(parents=True, exist_ok=True)
    report = {'schemaVersion': BUILD_SCHEMA, 'managedPaths': MANAGED, 'status': 'building',
              'createdAtUtc': datetime.now(timezone.utc).isoformat(), 'sourceKnowledgeBase': str(kb),
              'newSemanticReview': False, 'structureReview': book['meta']['structureReview']}
    dump(report_path, report)
    archive = output / '书籍档案'; archive.mkdir()
    shutil.copytree(kb, archive / 'knowledge')
    created_readable = ensure_readable_exports(book, archive / 'knowledge')
    dump(archive / 'book.json', book)
    (archive / '全书档案.md').write_text(archive_markdown(book), encoding='utf-8')
    dump(archive / 'wiki-export.json', wiki_export(book))
    (archive / 'Wiki复用说明.md').write_text('# 单书档案供主题 Wiki 复用\n\n'
        '本包只保留这一位作者、这一本书的来源与内容，不写入现有 Wiki。\n\n'
        '- `book.json` 保留当前全部单元的完整规范记录、作者结构与原文页切片。\n'
        '- `wiki-export.json` 提供书籍命名空间中的单元、主张和概念候选；原ID另行保留。\n'
        '- `knowledge/` 保留原底库的全部文件；缺少的索引和单元Markdown从同源记录派生，不升级审核状态。\n'
        '- `bookAuthor`仅表示书籍署名，不等于每条引文发言者；`unitAttribution`保留章或附属材料的叙述语境，实际身份继续查阅原记录与定位。\n'
        '- 后续主题 Wiki 应选择相关内容、比较不同作者、保留冲突和限定，再决定是否归并；不能直接把本书观点改写成跨书共识或通用事实。\n'
        '- 新主线分组属于编辑归纳，当前状态：' + structure_label(book) + '；历史复核不升级为本轮重新审核。\n', encoding='utf-8')
    display_book = copy.deepcopy(book)
    for source in display_book['sources']:
        embedded = []
        for relative in source['visualPaths']:
            image = (output / relative).resolve()
            need(image.is_relative_to(output.resolve()), 'Image outside delivery')
            mime = mimetypes.guess_type(image.name)[0]
            need(mime in ('image/png', 'image/jpeg', 'image/webp'), 'Unsupported source image type')
            embedded.append('data:' + mime + ';base64,' + base64.b64encode(image.read_bytes()).decode('ascii'))
        source['visualPaths'] = embedded
    payload = json.dumps(display_book, ensure_ascii=False).replace('<', '\\u003c')
    (output / '阅读网页.html').write_text(template_text.replace('__BOOK_DATA__', payload), encoding='utf-8')
    copied = archive / 'knowledge'
    need(all(sha(copied / rel) == fingerprint for rel, fingerprint in book['provenance']['inputFingerprints'].items()), 'Copied archive fingerprint mismatch')
    report.update({'status': 'built-mechanical-checks-passed', 'bookId': book['meta']['bookId'],
                   'unitCount': len(book['units']), 'sourceCount': len(book['sources']),
                   'provenance': book['provenance'], 'derivedReadableFiles': created_readable, 'htmlSha256': sha(output / '阅读网页.html'),
                   'files': ['阅读网页.html', '书籍档案/book.json', '书籍档案/全书档案.md', '书籍档案/wiki-export.json', '书籍档案/Wiki复用说明.md']})
    report['managedFileHashes'] = {file.relative_to(output).as_posix(): sha(file) for file in sorted(output.rglob('*')) if file.is_file() and file != report_path and any(file.relative_to(output).parts[0] == name for name in MANAGED)}
    report['mechanicalBuildSeconds'] = round(time.perf_counter() - mechanical_started, 6)
    report['timingScope'] = 'Only reading existing files, mechanical consistency checks, copying and rendering; excludes original model reading/authoring/review.'
    dump(report_path, report)
    print(output / '阅读网页.html')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--knowledge-base', type=Path, required=True)
    parser.add_argument('--structure', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-pdf', type=Path)
    parser.add_argument('--title')
    parser.add_argument('--author')
    parser.add_argument('--representative-reading', type=Path, help='Reuse an existing guided-reading content file as the representative presentation')
    parser.add_argument('--cover-image', type=Path, help='Visually confirmed local book cover (PNG/JPEG/WebP); embeds offline')
    parser.add_argument('--cover-page', type=int, help='Physical PDF page of the confirmed cover, if applicable')
    parser.add_argument('--force', action='store_true', help='Replace only paths owned by a previous build from this tool')
    build(parser.parse_args())


if __name__ == '__main__':
    main()
