#!/usr/bin/env python3
"""Build, verify, prepare and deploy an authored book from one local configuration.

No content is authored or granted semantic approval by this script. Run without
--deploy for local artifacts only. Publishing uses an explicitly linked project.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace
import build_book_archive as builder

ROOT = Path(__file__).resolve().parents[1]

def need(ok, message):
    if not ok:
        raise ValueError(message)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def load_config(path):
    path = Path(path).resolve()
    config = read(path)
    need(config.get('schemaVersion') == 'learn-from-materials/book-pipeline-v1', 'Expected book-pipeline-v1')
    for key in ('knowledgeBase', 'structure', 'delivery', 'publicDir', 'stateDir'):
        need(isinstance(config.get(key), str) and config[key], 'Missing ' + key)
    for key in ('knowledgeBase', 'structure', 'delivery', 'publicDir', 'stateDir', 'sourcePdf', 'coverImage', 'representativeReading', 'browserReview'):
        if config.get(key):
            value = Path(config[key]).expanduser()
            config[key] = (path.parent / value).resolve() if not value.is_absolute() else value.resolve()
    dirs = [config[k] for k in ('knowledgeBase', 'delivery', 'publicDir', 'stateDir')]
    need(all(a != b and a not in b.parents and b not in a.parents for i, a in enumerate(dirs) for b in dirs[i+1:]), 'Input/output/state directories must be separate and non-nested')
    return config

def build(config):
    builder.build(SimpleNamespace(knowledge_base=config['knowledgeBase'], structure=config['structure'],
        output_dir=config['delivery'], source_pdf=config.get('sourcePdf'), title=None, author=None,
        representative_reading=config.get('representativeReading'), cover_image=config.get('coverImage'),
        cover_page=config.get('coverPage'), force=(config['delivery'] / '构建报告.json').is_file()))

def verify(config):
    delivery = config['delivery']
    report = read(delivery / '构建报告.json')
    for relative, fingerprint in report['managedFileHashes'].items():
        need(sha(delivery / relative) == fingerprint, 'Changed generated artifact: ' + relative)
    book = read(delivery / '书籍档案/book.json')
    ids = [r['unit']['id'] for r in book['units']]
    members = [uid for part in builder.ordered_parts(book['structure']) for uid in part['unitIds']]
    need(len(members) == len(set(members)) and set(members) == set(ids), 'Chapter/unit membership mismatch')
    for source in book['sources']:
        need(hashlib.sha256(source['text'].encode()).hexdigest() == source['contentSha256'], 'Changed source slice')
    html = (delivery / '阅读网页.html').read_text()
    data = re.search(r'<script type="application/json" id="book-data">(.*?)</script>', html, re.S)
    need(data, 'Missing embedded book data')
    embedded = json.loads(data[1])
    need(embedded['units'] == book['units'] and embedded['structure'] == book['structure'], 'HTML/archive content mismatch')
    for source in embedded['sources']:
        need(all(p.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')) for p in source['visualPaths']), 'Source images must be embedded offline')
    wiki = read(delivery / '书籍档案/wiki-export.json')
    need(len(wiki['units']) == len(ids), 'Wiki unit count mismatch')
    # A syntax check is useful, but is not a browser or content review.
    node = shutil.which('node')
    if node:
        scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
        for script in scripts:
            subprocess.run([node, '--check'], input=script, text=True, check=True, capture_output=True)
    result = {'status': 'mechanical-checks-passed', 'htmlSha256': sha(delivery / '阅读网页.html'),
        'units': len(ids), 'sourcePages': len(book['sources']), 'javascriptSyntax': 'passed' if node else 'not-run',
        'browserReview': 'separate-evidence-required-for-deployment', 'semanticReview': 'not-granted-by-script'}
    dump(config['stateDir'] / 'verification.json', result)
    return result

def payload_html(html, book):
    payload = json.dumps(book, ensure_ascii=False).replace('<', '\\u003c')
    html, count = re.subn(r'(<script type="application/json" id="book-data">).*?(</script>)',
                         lambda m: m[1] + payload + m[2], html, count=1, flags=re.S)
    need(count == 1, 'Missing single book data slot')
    return html

def manifest(directory):
    return {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and '.vercel' not in p.relative_to(directory).parts}

def privacy_check(public):
    for file in public.rglob('*'):
        need(not file.is_symlink(), 'Symlink in publication')
        if file.is_file() and file.suffix in ('.json', '.txt', '.md', '.html'):
            content = file.read_text()
            need(not re.search(r'/Users/|/home/|/root/|file:///|[A-Za-z]:\\\\', content), 'Private path in ' + file.name + '; review the source before publishing')

def _prepare(config, public):
    delivery = config['delivery']
    archive = public / '书籍档案'; knowledge = archive / 'knowledge'
    knowledge.mkdir(parents=True)
    book = copy.deepcopy(read(delivery / '书籍档案/book.json'))
    book['meta']['sourcePdf'] = ''
    book['structure']['confirmationEvidence'] = ('主线与代表讲解已有确认记录。' if book['meta']['structureReview'] == 'confirmed-by-user' else '主线尚待确认。')
    for record in book['units']:
        record.get('review', {}).pop('reader', None)
        record.get('review', {}).pop('executionMode', None)
    for source in book['sources']:
        source['file'] = Path(source['file']).name
    original_provenance = book['provenance']
    book['provenance'] = {key: original_provenance[key] for key in ('originalPdfFingerprint', 'sourceSliceHashes', 'newSemanticReview', 'mappingCheck')}
    book['provenance']['sourceKnowledgeBase'] = '书籍档案/knowledge'
    book['provenance']['publicDerivative'] = '公开派生去除本机路径、执行者身份与内部工作文件；不授予新审核状态。'
    source = delivery / '书籍档案/knowledge'
    for directory in ('units', 'visual'):
        if (source / directory).is_dir():
            shutil.copytree(source / directory, knowledge / directory)
    for name in ('INDEX.md', 'full_text.txt', 'full_text.md', 'source-heading-index.json'):
        if (source / name).is_file():
            shutil.copy2(source / name, knowledge / name)
    mapping = read(source / 'source_map.json')
    for row in mapping:
        row['source_file'] = Path(row['source_file']).name
    dump(knowledge / 'source_map.json', mapping)
    original = read(source / 'source_manifest.json')
    keep = ('filename', 'source_file', 'format', 'pages', 'sha256', 'text_sha256', 'extraction_method', 'chars')
    dump(knowledge / 'source_manifest.json', {'schemaVersion': 'public-source-manifest-v1',
        'sources': [{k: v for k, v in row.items() if k in keep} for row in original['sources']]})
    for record in book['units']:
        dump(knowledge / 'unit-records' / (record['unit']['id'] + '.json'), record)
    book['provenance']['inputFingerprints'] = manifest(knowledge)
    book['provenance']['structureSha256'] = builder.digest(book['structure'])
    dump(archive / 'book.json', book)
    wiki = read(delivery / '书籍档案/wiki-export.json')
    wiki['book'] = copy.deepcopy(book['meta']); wiki['inheritedReview'] = None
    for row in wiki['sources']:
        row['file'] = Path(row['file']).name
    dump(archive / 'wiki-export.json', wiki)
    for name in ('全书档案.md', 'Wiki复用说明.md'):
        shutil.copy2(delivery / '书籍档案' / name, archive / name)
    display = copy.deepcopy(book)
    for row in display['sources']:
        paths = []
        for relative in row['visualPaths']:
            image = (public / relative).resolve()
            need(image.is_relative_to(public.resolve()), 'Image outside public directory')
            mime = __import__('mimetypes').guess_type(image.name)[0]
            paths.append('data:' + mime + ';base64,' + base64.b64encode(image.read_bytes()).decode())
        row['visualPaths'] = paths
    html = payload_html((delivery / '阅读网页.html').read_text(), display)
    html = html.replace('<div class="download-row">', '<div class="download-row"><a href="learning-archive.zip" download>下载完整学习档案 ↧</a>', 1)
    (public / 'index.html').write_text(html)
    for name in ('LICENSE.md', 'NOTICE.md'):
        shutil.copy2(ROOT / name, public / name)
    dump(public / 'vercel.json', {'framework': None, 'buildCommand': None, 'installCommand': None, 'outputDirectory': '.'})
    (public / '.vercelignore').write_text('.vercel\n.git\n.env\n.env.*\n*.log\n.DS_Store\n')
    privacy_check(public)
    with zipfile.ZipFile(public / 'learning-archive.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(public.rglob('*')):
            if file.is_file() and file.name not in ('learning-archive.zip', 'vercel.json', '.vercelignore'):
                bundle.write(file, file.relative_to(public))
    return {'status': 'public-files-prepared', 'files': len(manifest(public))}

def prepare(config):
    verify(config)
    public = config['publicDir']; saved = config['stateDir'] / 'public-manifest.json'
    if public.exists():
        need(saved.is_file() and manifest(public) == read(saved), 'Public directory has unowned/edited files; choose a fresh publicDir')
    public.parent.mkdir(parents=True, exist_ok=True)
    # A failed preparation never replaces a previous working publication.
    with tempfile.TemporaryDirectory(prefix='.book-public-', dir=public.parent) as temp:
        staged = Path(temp) / 'site'
        result = _prepare(config, staged)
        if public.exists():
            shutil.rmtree(public)
        shutil.move(str(staged), public)
    dump(saved, manifest(public))
    return {**result, 'directory': str(public)}

def deploy(config):
    public = config['publicDir']; state = config['stateDir']
    need((state / 'public-manifest.json').is_file(), 'Run prepare first')
    need(manifest(public) == read(state / 'public-manifest.json'), 'Public artifacts changed after preparation')
    book = read(public / '书籍档案/book.json')
    need(book['meta']['structureReview'] == 'confirmed-by-user', 'Author structure has not been confirmed')
    readiness = config.get('contentReadiness', {})
    need(readiness.get('status') == 'ready' and readiness.get('note'), 'Record actual content scope and limitations in contentReadiness before deployment')
    browser = read(config['browserReview']) if config.get('browserReview') else {}
    need(browser.get('htmlSha256') == sha(public / 'index.html') and
         all(browser.get(k) is True for k in ('desktop', 'mobile', 'navigation', 'sources')), 'Supply current public HTML browser review: hash plus desktop/mobile/navigation/sources=true')
    target = config.get('deployment', {})
    for key in ('projectId', 'projectName', 'teamId', 'productionUrl'):
        need(isinstance(target.get(key), str) and target[key].strip(), 'Missing deployment.' + key)
    url = urllib.parse.urlparse(target['productionUrl'])
    need(url.scheme == 'https' and url.hostname and not url.username and not url.password and url.path in ('', '/') and not url.query and not url.fragment, 'productionUrl must be a plain HTTPS origin')
    executable = shutil.which('vercel')
    need(executable, 'Install/authenticate Vercel CLI outside this workflow first')
    link = public / '.vercel/project.json'
    identity = {k: target[v] for k, v in (('projectId', 'projectId'), ('orgId', 'teamId'), ('projectName', 'projectName'))}
    if link.exists():
        existing = read(link)
        need(all(existing.get(k) == v for k, v in identity.items()), 'Existing Vercel project link differs from configuration')
    else:
        dump(link, identity)
    inspected = subprocess.run([executable, 'project', 'inspect', '--non-interactive', '--scope', target['teamId']], cwd=public, capture_output=True, text=True, check=True)
    need(target['projectId'] in inspected.stdout + inspected.stderr, 'Vercel project identity was not confirmed')
    # CLI checks actual remote project; never creates a project or downloads env vars.
    result = subprocess.run([executable, 'deploy', '--prod', '--yes', '--non-interactive', '--scope', target['teamId'], '--json'], cwd=public, capture_output=True, text=True)
    (state / 'vercel-deploy.log').write_text(result.stderr)
    result.check_returncode()
    response = json.loads(result.stdout)
    dump(state / 'vercel-deployment.json', response)
    data = response.get('deployment', {})
    need(data.get('readyState') == 'READY' and data.get('target') == 'production', 'Deployment is not READY production; inspect saved response')
    need(data.get('productionUrl', '').rstrip('/') == target['productionUrl'].rstrip('/'), 'Production alias differs from explicit target')
    checks = []
    # Anonymous HTTP read-back catches login redirects, stale aliases and asset omissions.
    for relative in ('index.html', '书籍档案/book.json', '书籍档案/wiki-export.json', 'learning-archive.zip'):
        address = target['productionUrl'].rstrip('/') + '/' + urllib.parse.quote(relative)
        with urllib.request.urlopen(address, timeout=60) as remote:
            value = hashlib.sha256(remote.read()).hexdigest()
        need(value == sha(public / relative), 'Online artifact differs: ' + relative)
        checks.append(relative)
    final = {'status': 'deployed-and-verified', 'url': target['productionUrl'], 'deploymentId': data.get('id'), 'readyState': 'READY', 'anonymousSha256Matches': checks}
    dump(state / 'publication.json', final)
    return final

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--stage', choices=('run', 'build', 'verify', 'prepare', 'deploy'), default='run')
    parser.add_argument('--deploy', action='store_true', help='Publish after local run; requires current browser evidence and explicit target')
    args = parser.parse_args(); config = load_config(args.config)
    need(not args.deploy or args.stage == 'run', '--deploy is only valid with --stage run')
    if args.stage == 'run':
        build(config); result = prepare(config)
        if args.deploy:
            result = deploy(config)
    else:
        result = globals()[args.stage](config)
    print(json.dumps(result or {'status': 'built'}, ensure_ascii=False))

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Book pipeline stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
