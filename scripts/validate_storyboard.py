#!/usr/bin/env python3
"""Validate storyboard timing and explicitly declared continuity states."""
import argparse
import json
import math
import sys
from pathlib import Path


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(plan, override=None):
    errors = []
    if not isinstance(plan, dict):
        return ['Plan must be a JSON object.']
    limit = override if override is not None else plan.get('max_clip_seconds', 10)
    if not number(limit) or limit <= 0:
        return ['max_clip_seconds must be a positive number.']
    segments = plan.get('segments')
    if not isinstance(segments, list) or not segments:
        return ['segments must be a nonempty array.']
    characters = plan.get('characters', [])
    if not isinstance(characters, list):
        return ['characters must be an array.']
    ids = set()
    for i, c in enumerate(characters):
        if not isinstance(c, dict) or not isinstance(c.get('id'), str) or not c['id'].strip():
            errors.append(f'characters[{i}]: id must be a nonempty string.')
        elif c['id'] in ids:
            errors.append(f'characters[{i}]: duplicate character id {c["id"]}.')
        else:
            ids.add(c['id'])
    seen = set()
    previous_end = None
    previous_state = None
    eps = 1e-6
    for i, seg in enumerate(segments):
        label = f'segments[{i}]'
        if not isinstance(seg, dict):
            errors.append(f'{label}: must be an object.')
            previous_end = None
            previous_state = None
            continue
        ident = seg.get('id')
        if not isinstance(ident, str) or not ident.strip():
            errors.append(f'{label}: id must be a nonempty string.')
        elif ident in seen:
            errors.append(f'{label}: duplicate segment id {ident}.')
        else:
            seen.add(ident)
        start, end = seg.get('start'), seg.get('end')
        valid_time = number(start) and number(end)
        if not valid_time:
            errors.append(f'{label}: start and end must be finite numbers.')
        else:
            if start < 0 or end <= start:
                errors.append(f'{label}: expected 0 <= start < end.')
            if end - start > limit + eps:
                errors.append(f'{label}: duration {end-start:g}s exceeds limit {limit:g}s.')
            if i == 0 and abs(start) > eps:
                errors.append(f'{label}: first segment must start at 0.')
            if i > 0 and previous_end is not None and abs(start - previous_end) > eps:
                kind = 'gap' if start > previous_end else 'overlap'
                errors.append(f'{label}: {kind} between {previous_end:g}s and {start:g}s.')
        transition = seg.get('transition_from_previous')
        valid_transition = 'start' if i == 0 else 'continuous or cut'
        if (i == 0 and transition != 'start') or (i > 0 and transition not in ('continuous', 'cut')):
            errors.append(f'{label}: transition_from_previous must be {valid_transition}.')
        cast = seg.get('characters', [])
        if not isinstance(cast, list) or any(not isinstance(c, str) for c in cast):
            errors.append(f'{label}: characters must be an array of string IDs.')
        else:
            for c in cast:
                if c not in ids:
                    errors.append(f'{label}: unknown character {c}.')
        if i > 0 and transition in ('continuous', 'cut'):
            keys = seg.get('continuity_keys', [])
            start_state = seg.get('start_state')
            invalid_keys = not isinstance(keys, list) or any(not isinstance(k, str) or not k for k in keys)
            if invalid_keys or (transition == 'continuous' and not keys):
                errors.append(f'{label}: continuous transitions require nonempty string continuity_keys; cuts may use a string list.')
            elif keys:
                if not isinstance(start_state, dict) or not isinstance(previous_state, dict):
                    errors.append(f'{label}: continuity_keys require start_state and previous end_state objects.')
                else:
                    for k in keys:
                        if k not in start_state or k not in previous_state:
                            errors.append(f'{label}: missing continuity key {k} on one or both sides.')
                        elif start_state[k] is None or previous_state[k] is None:
                            errors.append(f'{label}: continuity key {k} is unknown (null).')
                        elif start_state[k] != previous_state[k]:
                            errors.append(f'{label}: continuity mismatch for {k}.')
        previous_end = end if valid_time else None
        previous_state = seg.get('end_state')
    total = plan.get('total_duration_seconds')
    if not number(total) or total <= 0:
        errors.append('total_duration_seconds must be a positive number.')
    elif previous_end is not None and abs(total - previous_end) > eps:
        errors.append(f'Last end {previous_end:g}s differs from total {total:g}s.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--max-seconds', type=float, default=None)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
        errors = validate(plan, args.max_seconds)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Cannot read plan: {exc}', file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f'ERROR: {error}', file=sys.stderr)
        return 1
    for i, seg in enumerate(plan['segments']):
        if i > 0 and seg.get('transition_from_previous') == 'cut' and not seg.get('continuity_keys'):
            print(f'WARNING: segments[{i}] is a cut with no declared continuity keys; cross-shot identity and objects were not checked.', file=sys.stderr)
    print(f'OK: {len(plan["segments"])} segments; structural timing and declared continuity match. Visual/model behavior not validated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
