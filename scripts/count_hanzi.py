#!/usr/bin/env python3
"""Count Han characters in a UTF-8 prompt file; exclude whitespace and punctuation."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('prompt_file', type=Path)
args = parser.parse_args()
text = args.prompt_file.read_text(encoding='utf-8-sig')
count = sum(('\u3400' <= c <= '\u4dbf') or ('\u4e00' <= c <= '\u9fff') or ('\U00020000' <= c <= '\U0002fa1f') for c in text)
print(f'Han characters: {count}')
