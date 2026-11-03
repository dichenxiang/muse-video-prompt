#!/usr/bin/env python3
"""Extract actual decoded boundary frames and compare stills in RGB24."""
import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


def run(args):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc:
        raise ValueError(f"Required executable not found: {args[0]}") from exc
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace')[-3000:].strip())
    return result.stdout


def probe(path, count=False):
    args = ['ffprobe', '-v', 'error', '-select_streams', 'v:0']
    if count:
        args += ['-count_frames']
    args += ['-show_entries', 'stream=width,height,avg_frame_rate,nb_read_frames', '-of', 'json', str(path)]
    streams = json.loads(run(args)).get('streams', [])
    if not streams:
        raise ValueError(f'No video stream found: {path}')
    return streams[0]


def extract(args):
    src = Path(args.video)
    out = Path(args.first if args.first is not None else args.last)
    if not src.is_file():
        raise ValueError(f'Input file not found: {src}')
    if out.suffix.lower() != '.png':
        raise ValueError('Output must have a .png extension.')
    if out.exists():
        raise ValueError(f'Output already exists; refusing to overwrite: {out}')
    if not out.parent.exists():
        raise ValueError(f'Output directory does not exist: {out.parent}')
    meta = probe(src, count=True)
    try:
        count = int(meta['nb_read_frames'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Unable to count decoded frames; cannot identify the last frame.') from exc
    if count < 1:
        raise ValueError('Video contains no decoded frames.')
    index = 0 if args.first is not None else count - 1
    filt = f'select=eq(n\\,{index})'
    run(['ffmpeg', '-v', 'error', '-n', '-i', str(src), '-map', '0:v:0', '-vf', filt,
         '-fps_mode', 'passthrough', '-frames:v', '1', '-update', '1', str(out)])
    if not out.is_file() or out.stat().st_size == 0:
        raise ValueError('FFmpeg did not produce a frame.')
    print(json.dumps({'input': str(src), 'output': str(out), 'decoded_frames': count,
                      'frame_index': index, 'width': meta.get('width'),
                      'height': meta.get('height'), 'average_frame_rate': meta.get('avg_frame_rate')},
                     ensure_ascii=False))


def rgb_frame(path, width, height):
    raw = run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-frames:v', '1',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
    if len(raw) != width * height * 3:
        raise ValueError(f'Unexpected decoded image size: {path}')
    return raw


def compare(args):
    first, second = Path(args.reference), Path(args.candidate)
    if not first.is_file() or not second.is_file():
        raise ValueError('Both input images must exist.')
    if first.suffix.lower() != '.png' or second.suffix.lower() != '.png':
        raise ValueError('Comparison expects two PNG boundary images.')
    a, b = probe(first), probe(second)
    size_a = (a.get('width'), a.get('height'))
    size_b = (b.get('width'), b.get('height'))
    if size_a != size_b or not all(isinstance(n, int) and n > 0 for n in size_a):
        raise ValueError(f'Image dimensions differ or are invalid: {size_a} vs {size_b}; no automatic scaling.')
    raw_a = rgb_frame(first, *size_a)
    raw_b = rgb_frame(second, *size_a)
    squared_error = sum((x-y)**2 for x, y in zip(raw_a, raw_b))
    mse = squared_error / len(raw_a)
    psnr = None if squared_error == 0 else 10 * math.log10(255**2 / mse)
    print(json.dumps({'reference': str(first), 'candidate': str(second), 'width': size_a[0],
                      'height': size_a[1], 'comparison_space': 'decoded RGB24',
                      'pixel_identical_in_comparison_space': squared_error == 0,
                      'psnr_db': 'inf' if psnr is None else round(psnr, 3),
                      'note': 'A pixel metric does not establish semantic or motion continuity.'},
                     ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    ex = subs.add_parser('extract', help='Extract first or actual last decoded video frame as PNG')
    ex.add_argument('video')
    group = ex.add_mutually_exclusive_group(required=True)
    group.add_argument('--first', metavar='OUTPUT.png')
    group.add_argument('--last', metavar='OUTPUT.png')
    cmp = subs.add_parser('compare', help='Compare equal-size PNGs without resizing')
    cmp.add_argument('reference')
    cmp.add_argument('candidate')
    args = parser.parse_args()
    try:
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            raise ValueError('ffmpeg and ffprobe must both be available on PATH.')
        extract(args) if args.command == 'extract' else compare(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
