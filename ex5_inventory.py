"""Write a plain-text inventory of Yamaha EX5 save files.

Every EX5 file starts with a 16-byte 'SY1200xxx  V1.00' block header:
  PTN  pattern (.S1P)            -> ex5_to_midi.py
  SPA  samples/waveforms (.S1M)  -> ex5_samples.py
  VCA  user voice bank (.S1V)
  SYT  system: performances + voices (.S1Y)
  KMAP key map
  SEQ  song + pattern sequencer memory
  ALL  all-data container (.S1A) holding SYT, KMAP, SPA and SEQ blocks

Voice and performance names are found by record signatures, not a full
parse, so a few names may be missing.

Usage: python3 ex5_inventory.py FILE_OR_DIR ... [-o FILE]
"""
import argparse
import os
import re

from ex5_pattern import load_any
from ex5_samples import samples

HEADER = re.compile(rb'SY1200([A-Z]{3,4}) *V1\.00')
VOICE = re.compile(rb'\x7f[\x00-\xff]([A-Za-z0-9"\'!&\-][ -~]{11})', re.S)
PERFORMANCE = re.compile(rb'([ -~]{12})\x16\x7f\x01\x01')


def blocks(data):
    """[(kind, start, end)] for each SY1200 block header in the file."""
    hs = [(m.group(1).decode(), m.start()) for m in HEADER.finditer(data)]
    hs = [h for h in hs if h[0] != 'ALL']
    return [(k, s, hs[i + 1][1] if i + 1 < len(hs) else len(data)) for i, (k, s) in enumerate(hs)]


def names(regex, data):
    out = [m.group(1).decode('latin-1').strip() for m in regex.finditer(data)]
    return [n for n in out if n and '@@' not in n]


def wrap(items, indent='    ', width=78):
    lines, cur = [], indent
    for it in items:
        piece = it + ', '
        if len(cur) + len(piece) > width and cur.strip():
            lines.append(cur.rstrip())
            cur = indent
        cur += piece
    if cur.strip():
        lines.append(cur.rstrip(', '))
    return lines


def describe(path):
    with open(path, 'rb') as f:
        data = f.read()
    out = [f'{os.path.relpath(path)}  ({len(data):,} bytes)']
    if not data.startswith(b'SY1200'):
        return out + ['  not an EX5 file']
    for kind, start, end in blocks(data):
        blk = data[start:end]
        if kind == 'PTN' or (kind == 'SEQ' and start):
            try:
                pat, _ = load_any(path)
            except ValueError as e:
                out.append(f'  {kind}: unreadable pattern ({e})')
                continue
            label = 'pattern' if kind == 'PTN' else 'song/pattern memory, holding a pattern'
            out.append(f'  {kind}: {label}, {len(pat.sections)} sections')
            for s in pat.sections:
                tracks = [str(t + 1) for t, p in enumerate(s.phrases) if p and (p.notes or p.events)]
                if tracks:
                    name = '' if s.name == 'NewTrack' else f' {s.name}'
                    out.append(f'    S{s.index + 1:02d}{name:10} {s.bars:2d} bars {s.tempo:g} BPM, tracks {",".join(tracks)}')
        elif kind == 'SPA':
            smp = list(samples(blk))
            bits = '/'.join(f'{b}' for b in sorted({s[4] for s in smp}, reverse=True)) or '16'
            out.append(f'  SPA: {len(smp)} samples ({bits}-bit)')
            out += wrap(f'{n + 1}:{name}' for n, name, *_ in smp)
        elif kind == 'VCA':
            v = names(VOICE, b'\x7f\x00' + blk[0x880:])
            out.append(f'  VCA: user voice bank, {len(v)} named voices')
            out += wrap(v)
        elif kind == 'SYT':
            greet = blk[0x84:0xAC].decode('latin-1').strip()
            perf = names(PERFORMANCE, blk)
            out.append(f'  SYT: system settings; greeting "{" ".join(greet.split())}"')
            out.append(f'    {len(perf)} named performances:')
            out += wrap(perf, '      ')
            last = max((m.end() for m in PERFORMANCE.finditer(blk)), default=0)
            v = names(VOICE, blk[last:])
            if v:
                out.append(f'    voice bank, {len(v)} named voices:')
                out += wrap(v, '      ')
        elif kind == 'KMAP':
            out.append('  KMAP: key map (not decoded)')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out', default='Output/INVENTORY.txt')
    args = ap.parse_args()
    files = []
    for p in args.inputs:
        if os.path.isdir(p):
            files += sorted(os.path.join(r, f) for r, _, fs in os.walk(p) for f in fs if not f.startswith('.'))
        else:
            files.append(p)
    lines = []
    for f in files:
        lines += describe(f) + ['']
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w') as fh:
        fh.write('\n'.join(lines))
    print(f'wrote {args.out} ({len(files)} files)')


if __name__ == '__main__':
    main()
