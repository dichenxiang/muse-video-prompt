#!/usr/bin/env python3
"""Decode every video frame into timestamped contact sheets for visual review."""
import argparse, hashlib, json, math, shutil, subprocess, sys
from pathlib import Path


def run(args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(p.stderr[-4000:])
    return p.stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('video', type=Path)
    p.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    p.add_argument('--width', type=int, default=320, help='Thumbnail width, default 320')
    p.add_argument('--columns', type=int, default=4)
    p.add_argument('--rows', type=int, default=4)
    args = p.parse_args()
    if not args.video.is_file(): p.error('Input video does not exist')
    if not (80 <= args.width <= 1280 and 1 <= args.columns <= 8 and 1 <= args.rows <= 8): p.error('Invalid thumbnail/sheet dimensions')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool): raise RuntimeError(f'{tool} not found on PATH')
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:
        raise RuntimeError('Pillow is required: python -m pip install Pillow') from e
    out = args.out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())): raise RuntimeError('Output directory must be new or empty; refusing to overwrite')
    out.mkdir(parents=True, exist_ok=True)
    frames = out / 'frames'; frames.mkdir()
    sheets = out / 'sheets'; sheets.mkdir()
    source = args.video.resolve()
    digest = hashlib.sha256()
    with source.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): digest.update(chunk)
    meta = json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(source)]))
    videos = [s for s in meta.get('streams',[]) if s.get('codec_type') == 'video' and not s.get('disposition',{}).get('attached_pic')]
    if not videos: raise RuntimeError('No video stream found')
    index = videos[0]['index']
    stamps_data = json.loads(run(['ffprobe','-v','error','-select_streams',str(index),'-show_frames','-show_entries','frame=best_effort_timestamp_time,pkt_duration_time','-of','json',str(source)]))
    timestamps = [f.get('best_effort_timestamp_time') for f in stamps_data.get('frames',[])]
    run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-i',str(source),'-map',f'0:{index}','-vf',f'scale={args.width}:-2','-fps_mode','passthrough','-q:v','3',str(frames/'frame_%08d.jpg')])
    files = sorted(frames.glob('frame_*.jpg'))
    if not files: raise RuntimeError('No decoded frames')
    if len(files) != len(timestamps): raise RuntimeError(f'Timestamp/frame count mismatch: {len(timestamps)} vs {len(files)}; do not claim complete timestamp coverage')
    entries=[]; capacity=args.columns*args.rows
    for start in range(0,len(files),capacity):
        batch=files[start:start+capacity]
        with Image.open(batch[0]) as im: w,h=im.size
        canvas=Image.new('RGB',(w*args.columns,(h+28)*args.rows),'white'); draw=ImageDraw.Draw(canvas)
        sheet_name=f'sheet_{start//capacity+1:05d}.jpg'
        for offset,path in enumerate(batch):
            i=start+offset; x=(offset%args.columns)*w; y=(offset//args.columns)*(h+28)
            with Image.open(path) as im: canvas.paste(im.convert('RGB'),(x,y))
            ts=timestamps[i]; label=f'#{i+1}  t={float(ts):.3f}s' if ts is not None else f'#{i+1}  t=unknown'
            draw.text((x+4,y+h+5),label,fill='black')
            entries.append({'frame':i+1,'timestamp_seconds':float(ts) if ts is not None else None,'image':str(path.relative_to(out)),'sheet':f'sheets/{sheet_name}'})
        canvas.save(sheets/sheet_name,quality=90)
    manifest={'source':str(source),'sha256':digest.hexdigest(),'video_stream_index':index,'metadata':meta,'decoded_frames':len(files),'timestamped_frames':sum(t is not None for t in timestamps),'sheets':math.ceil(len(files)/capacity),'frames':entries,'note':'Every decoded frame is present; sheets and metadata are evidence, not semantic interpretation. Timestamps are source presentation timestamps and may not start at zero.'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(out),'decoded_frames':len(files),'timestamped_frames':manifest['timestamped_frames'],'sheets':manifest['sheets']},ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except (RuntimeError, OSError, ValueError) as e:
        print(f'Error: {e}',file=sys.stderr); sys.exit(1)
