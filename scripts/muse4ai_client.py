#!/usr/bin/env python3
"""Local Muse4AI REST adapter. Set MUSE4AI_API_KEY in the process environment."""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:47821'
ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
REQUEST_ID = re.compile(r'^[!-~]{1,100}$')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Server redirect refused; credentials are restricted to the local Muse4AI server.')


def ident(value):
    if not ID.fullmatch(value):
        raise ValueError('ID must contain only letters, digits, underscores or hyphens (1–100).')
    return value


def request_id(value):
    if not REQUEST_ID.fullmatch(value):
        raise ValueError('Request ID must be 1–100 printable ASCII characters without spaces.')
    return value


def call(method, path, data=None, content_type=None, idem=None):
    key = os.environ.get('MUSE4AI_API_KEY', '')
    if not key:
        raise ValueError('MUSE4AI_API_KEY is not set. Configure the key securely outside chat.')
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}
    if content_type:
        headers['Content-Type'] = content_type
    if idem:
        headers['Idempotency-Key'] = request_id(idem)
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=65) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raw = e.read(65536)
        try:
            problem = json.loads(raw)
            code = problem.get('code', 'unknown')
        except (json.JSONDecodeError, UnicodeDecodeError):
            code = 'unknown'
        raise ValueError(f'Muse4AI HTTP {e.code}; code={code}. Check app for details; do not blindly resubmit.') from None
    except urllib.error.URLError:
        raise ValueError('Muse4AI connection failed. For a submission with uncertain outcome, reuse the same request ID; do not create a new one blindly.') from None


def display(obj):
    # Signed download URLs and full prompt text are deliberately not echoed.
    if isinstance(obj, dict):
        return {k: display(v) for k, v in obj.items() if k not in ('download_url', 'prompt', 'authorization', 'token', 'api_key')}
    if isinstance(obj, list):
        return [display(v) for v in obj]
    return obj


def read_prompt(path, maximum=None):
    prompt = Path(path).read_text(encoding='utf-8-sig').strip()
    if not prompt:
        raise ValueError('Prompt file is empty.')
    # JavaScript string.length counts UTF-16 code units, not Python Unicode code points.
    length = len(prompt.encode('utf-16-le')) // 2
    if maximum and length > maximum:
        raise ValueError(f'Prompt exceeds {maximum} UTF-16 code units ({length}); prepare a shorter version explicitly; no automatic truncation.')
    return prompt


def json_call(method, path, payload=None, idem=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    raw = call(method, path, data, 'application/json' if data is not None else None, idem)
    return json.loads(raw.decode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    upload = sub.add_parser('upload', help='Upload an existing PNG/JPEG/WEBP or MP4 as a reference')
    upload.add_argument('file')
    submit = sub.add_parser('submit', help='Submit exactly one image or video job')
    submit.add_argument('--kind', choices=['image', 'video'], required=True)
    submit.add_argument('--prompt-file', required=True)
    submit.add_argument('--request-id', required=True)
    submit.add_argument('--reference-id')
    submit.add_argument('--account')
    job = sub.add_parser('job')
    job.add_argument('id')
    job.add_argument('--wait', type=int, default=0, choices=range(0, 51))
    download = sub.add_parser('download')
    download.add_argument('asset_id')
    download.add_argument('--out', required=True)
    extend = sub.add_parser('extend', help='Submit one Muse4AI continuation step; output may be cumulative')
    extend.add_argument('asset_id')
    extend.add_argument('--request-id', required=True)
    extend.add_argument('--directive-file')
    chain = sub.add_parser('chain')
    chain.add_argument('id')
    chain.add_argument('--wait', type=int, default=0, choices=range(0, 51))
    args = parser.parse_args()
    try:
        if args.command == 'status':
            out = json_call('GET', '/v1/status')
        elif args.command == 'upload':
            path = Path(args.file)
            types = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp', '.mp4':'video/mp4'}
            mime = types.get(path.suffix.lower())
            if not mime or not path.is_file():
                raise ValueError('Reference must be an existing PNG, JPEG, WEBP, or MP4 file.')
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('Reference exceeds 20 MiB.')
            out = json.loads(call('POST', '/v1/references', path.read_bytes(), mime).decode('utf-8'))
        elif args.command == 'submit':
            payload = {'kind':args.kind, 'prompt':read_prompt(args.prompt_file, 4000), 'repeat':1, 'site':'muse'}
            if args.reference_id:
                payload['reference_id'] = ident(args.reference_id)
            if args.account:
                payload['account'] = args.account
            out = json_call('POST', '/v1/jobs', payload, args.request_id)
        elif args.command == 'job':
            out = json_call('GET', '/v1/jobs/' + ident(args.id) + '?wait=' + str(args.wait))
        elif args.command == 'extend':
            payload = {'mode':'directive', 'directive':read_prompt(args.directive_file), 'times':1} if args.directive_file else {'mode':'auto', 'times':1}
            out = json_call('POST', '/v1/assets/' + ident(args.asset_id) + '/extend', payload, args.request_id)
        elif args.command == 'chain':
            out = json_call('GET', '/v1/extend-chains/' + ident(args.id) + '?wait=' + str(args.wait))
        else:
            path = Path(args.out)
            if path.exists():
                raise ValueError('Output already exists; refusing to overwrite.')
            if not path.parent.is_dir():
                raise ValueError('Output directory does not exist.')
            raw = call('GET', '/v1/assets/' + ident(args.asset_id) + '/content')
            with path.open('xb') as f:
                f.write(raw)
            out = {'asset_id':args.asset_id, 'output':str(path), 'bytes':len(raw)}
        print(json.dumps(display(out), ensure_ascii=False))
        return 0
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
