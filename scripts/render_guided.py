#!/usr/bin/env python3
"""Render a standalone reading guide; mechanical checks do not certify meaning."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def render(data, template, source_map=None, full_text=None):
    require(data.get('schemaVersion') == 'learn-from-materials/guided-reading-v1', 'Expected guided-reading-v1, not overview schema 4.3')
    meta, view = data['meta'], data['presentation']
    require(meta.get('status') in ('prototype', 'reading-guide'), 'State prototype or reading-guide; neither means complete systematic coverage')
    for key in ('book', 'author', 'scope', 'note'):
        require(bool(meta.get(key)), 'Missing meta.' + key)
    for key in ('overviewTitle', 'overviewIntro', 'representativeLabel', 'representativeTitle', 'representativeIntro', 'sectionHeading', 'representativeScope'):
        require(bool(view.get(key)), 'Missing presentation.' + key)
    require(view.get('sectionEvidence') in ('material', 'synthesis'), 'Declare origin of section grouping')
    require(view.get('sectionRelation') in ('sequence', 'independent'), 'Declare whether section arrows are supported')
    for name in ('spine', 'sections', 'chapters', 'quotes'):
        require(isinstance(data.get(name), list) and data[name], 'Missing nonempty ' + name)
    quote_ids = [q['id'] for q in data['quotes']]
    require(len(quote_ids) == len(set(quote_ids)), 'Duplicate quote IDs')
    for q in data['quotes']:
        require(bool(q.get('text')) and bool(q.get('locator')), 'Every quote needs actual text and locator')
    spine_ids = [s['id'] for s in data['spine']]
    section_ids = [s['id'] for s in data['sections']]
    require(len(spine_ids) == len(set(spine_ids)) and len(section_ids) == len(set(section_ids)), 'Duplicate navigation IDs')
    require(meta.get('representativeSpineId') in spine_ids, 'Representative content must map to an existing spine node')
    for s in data['spine']:
        require(s.get('evidence') == 'synthesis', 'Reading-route grouping must be explicitly editorial synthesis')
        for key in ('title', 'kicker', 'question', 'summary', 'relation', 'chapterRefs', 'sourceIds'):
            require(bool(s.get(key)), 'Missing spine.' + key)
    for s in data['sections']:
        for key in ('title', 'short', 'question', 'explanation', 'details', 'distinction', 'sourceIds'):
            require(bool(s.get(key)), 'Missing section.' + key)
    for row in [data['keyDistinction'], *data['sections'], *[s['example'] for s in data['sections'] if s.get('example')], *data['readingNotes']]:
        require(row.get('evidence') in ('material', 'synthesis'), 'Each explanation and example needs an explicit evidence class')
        require(bool(row.get('sourceIds')), 'Each displayed explanation needs source references')
    for chapter in data['chapters']:
        require(bool(chapter.get('title')), 'Missing source heading')
        require(all(g in spine_ids for g in chapter['group']), 'Unknown chapter-to-spine mapping')
    def check_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('sourceIds', 'sectionSourceIds'):
                    require(isinstance(child, list) and all(i in quote_ids for i in child), 'Unknown quote ID')
                else:
                    check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)
    require(bool(view.get('sectionSourceIds')), 'Section grouping requires a source reference')
    check_refs(data)
    checked = 0
    if source_map is not None:
        blocks = {row['source_id']: row for row in source_map}
        for q in data['quotes']:
            require(q.get('sourceBlockId') in blocks, 'Unknown original source block: ' + q['id'])
            block = blocks[q['sourceBlockId']]
            text = full_text[block['start_char']:block['end_char']]
            require(q['text'] in text, 'Quote is not a continuous original substring: ' + q['id'])
            if q.get('context'):
                require(q['context'] in text, 'Context differs from original: ' + q['id'])
            if q.get('page') is not None:
                require(q['page'] == block.get('pdf_page'), 'PDF page mismatch: ' + q['id'])
            checked += 1
    def escaped(text):
        return html.escape(str(text)).replace('\n', '<br>')
    material_kind = meta.get('sourceType', 'book')
    strings = {
        '__PAGE_TITLE__': meta['book'] + ' · 交互导读', '__MATERIAL_TITLE__': meta['book'],
        '__EDITION__': '交互导读 · ' + ('样板' if meta['status'] == 'prototype' else '阅读版'),
        '__OVERVIEW_EYEBROW__': view.get('eyebrow', '先读主线，再逐层展开'),
        '__OVERVIEW_TITLE__': view['overviewTitle'], '__OVERVIEW_INTRO__': view['overviewIntro'],
        '__OUTLINE_HEADING__': '作者章名' if material_kind == 'book' else '原文标题',
        '__REPRESENTATIVE_SHORT__': '代表章节' if material_kind == 'book' else '代表内容',
        '__OUTLINE_COUNT__': str(len(data['chapters'])) + (' 章' if material_kind == 'book' else ' 个部分'),
        '__REPRESENTATIVE_LABEL__': view['representativeLabel'], '__REPRESENTATIVE_TITLE__': view['representativeTitle'],
        '__REPRESENTATIVE_INTRO__': view['representativeIntro'], '__SECTIONS_HEADING__': view['sectionHeading'],
        '__SECTION_CLASS__': view['sectionEvidence'], '__SECTION_ORIGIN__': ('原书转述' if material_kind == 'book' else '原文转述') if view['sectionEvidence'] == 'material' else '导读归纳',
        '__REPRESENTATIVE_SCOPE__': view['representativeScope'], '__MATERIAL_NOTE__': meta['note'],
        '__CREATOR__': meta['author'], '__BUILD_LABEL__': meta.get('edition', '交互导读'),
        '__TAKEAWAY_HEADING__': view.get('takeawayHeading', '读完这一节，带走这些关系。'),
    }
    result = template
    for token, value in strings.items():
        result = result.replace(token, escaped(value))
    result = result.replace('__ORIGINAL__', '原书' if material_kind == 'book' else '原文')
    result = result.replace('__WHOLE__', '全书' if material_kind == 'book' else '材料')
    require('__CONTENT_DATA__' in result, 'Missing data slot')
    require(not re.search(r'__[A-Z_]+__', result.replace('__CONTENT_DATA__', '')), 'Unresolved template field')
    result = result.replace('__CONTENT_DATA__', json.dumps(data, ensure_ascii=False).replace('<', '\\u003c'))
    return result, {'artifactType': 'guided-reading', 'status': meta['status'], 'quotesCheckedAgainstOriginal': checked, 'quoteCheck': 'passed' if source_map is not None else 'not-run', 'semanticReview': 'not-performed-by-renderer'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-map', type=Path)
    parser.add_argument('--full-text', type=Path)
    args = parser.parse_args()
    require(bool(args.source_map) == bool(args.full_text), 'Supply source-map and full-text together')
    template = Path(__file__).resolve().parents[1] / 'templates/guided-reader.html'
    result, report = render(json.loads(args.input.read_text()), template.read_text(), json.loads(args.source_map.read_text()) if args.source_map else None, args.full_text.read_text() if args.full_text else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result)
    report['htmlSha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.render.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
