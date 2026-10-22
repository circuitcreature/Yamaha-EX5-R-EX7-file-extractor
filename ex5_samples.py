"""Export samples from Yamaha EX5 sample/wave files (.S1M, header
'SY1200SPA  V1.00', also found as a block inside .S1A all-data files) to WAV.

SPA block layout (offsets relative to the block start):
  0x1086   keybanks: 8-byte name, u16 zone count, then 16-byte zones
           (40 nn = sample number, key range, level ...)
  0x8886   1024 sample records x 30 bytes:
             +0   name (8 bytes)
             +9   format flags: bit 7 set = 8-bit (bit 6 then selects
                  sign-magnitude, clear = two's complement); else bit 6
                  set = 12-bit packed; else 16-bit. Other bits unknown.
             +10  u24 address in sample memory (not needed for export)
             +13  u32 loop start; bit 30 set = no loop
             +17  u32 loop length (end = start + length)
             +21  root key (MIDI note)
             +28  u16 sample number (0xffff = unused record)
  0x10086  1024 x u32 sample data size in bytes, by sample number
  0x11086  sample data, back to back in sample-number order. Loop points
           count samples in every format. Formats, all mono and signed:
             16-bit  big-endian
             12-bit  4 samples in 6 bytes b0..b5:
                       s0 = b0.lo b1     s1 = b3 b0.hi
                       s2 = b5.lo b2     s3 = b4 b5.hi
             8-bit   sign-magnitude (bit 7 = negative) or two's complement

A bank can mix formats. The files store no sample rate; pitch analysis
against the root keys gives 44.1 kHz for 16-bit samples and 48 kHz for
12- and 8-bit ones. Override with --rate.

Usage: python3 ex5_samples.py FILE_OR_DIR ... [-o OUTDIR] [--rate HZ]
"""
import argparse
import os
import re
import struct
import sys

MAGIC = b'SY1200SPA'
RECORDS, SIZES, AUDIO = 0x8886, 0x10086, 0x11086
RATES = {16: 44100, 12: 48000, 8: 48000}


def sample_format(flags):
    """Return (bits, sign_magnitude) from a record's format byte."""
    if flags & 0x80:
        return 8, bool(flags & 0x40)
    return (12 if flags & 0x40 else 16), False


def decode(raw, bits, sign_mag=False):
    """Return 16-bit little-endian PCM bytes."""
    if bits == 8:
        if sign_mag:
            pcm = [(v & 0x7F) * (-256 if v & 0x80 else 256) for v in raw]
        else:
            pcm = [(v - 256 if v & 0x80 else v) * 256 for v in raw]
    elif bits == 12:
        pcm = []
        for i in range(0, len(raw) - 5, 6):
            b0, b1, b2, b3, b4, b5 = raw[i:i + 6]
            for v in ((b0 & 15) << 8 | b1, b3 << 4 | b0 >> 4, (b5 & 15) << 8 | b2, b4 << 4 | b5 >> 4):
                pcm.append(((v ^ 0x800) - 0x800) * 16)
    else:
        pcm = struct.unpack(f'>{len(raw) // 2}h', raw[:len(raw) // 2 * 2])
    return struct.pack(f'<{len(pcm)}h', *pcm)


def samples(spa):
    """Yield (number, name, root_key, loop or None, bits, pcm_le_bytes)."""
    sizes = struct.unpack('>1024I', spa[SIZES:SIZES + 4096])
    offsets, pos = [], AUDIO
    for s in sizes:
        offsets.append(pos)
        pos += s
    recs = {}
    for i in range(1024):
        r = spa[RECORDS + 30 * i:RECORDS + 30 * i + 30]
        num = struct.unpack('>H', r[28:30])[0]
        if num < 1024 and sizes[num]:
            recs[num] = r
    for num in sorted(recs):
        r = recs[num]
        bits, sign_mag = sample_format(r[9])
        pcm = decode(spa[offsets[num]:offsets[num] + sizes[num]], bits, sign_mag)
        lstart, llen = struct.unpack('>II', r[13:21])
        loop = (lstart, lstart + llen - 1) if not lstart & 0xFF000000 and llen > 0 else None
        if loop and loop[1] >= len(pcm) // 2:
            loop = None
        yield num, r[:8].decode('latin-1').rstrip(), r[21], loop, bits, pcm


def write_wav(path, pcm, rate, root, loop):
    fmt = struct.pack('<HHIIHH', 1, 1, rate, rate * 2, 2, 16)
    period = round(1e9 / rate)
    smpl = struct.pack('<9I', 0, 0, period, root, 0, 0, 0, 1 if loop else 0, 0)
    if loop:
        smpl += struct.pack('<6I', 0, 0, loop[0], loop[1], 0, 0)
    chunks = b'fmt ' + struct.pack('<I', len(fmt)) + fmt
    chunks += b'smpl' + struct.pack('<I', len(smpl)) + smpl
    chunks += b'data' + struct.pack('<I', len(pcm)) + bytes(pcm)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(chunks)) + b'WAVE' + chunks)


def export(path, outdir, rate):
    with open(path, 'rb') as f:
        data = f.read()
    at = data.find(MAGIC)
    if at < 0:
        raise ValueError('no sample (SPA) block')
    spa = data[at:]
    stem = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(outdir, stem)
    os.makedirs(dest, exist_ok=True)
    count = 0
    for num, name, root, loop, bits, pcm in samples(spa):
        safe = re.sub(r'[^A-Za-z0-9#!]+', '_', name).strip('_') or 'sample'
        sr = rate or RATES[bits]
        write_wav(os.path.join(dest, f'{num + 1:03d}_{safe}.wav'), pcm, sr, root, loop)
        secs = len(pcm) / 2 / sr
        print(f'  {num + 1:3d} {name:8}  key {root:3d}  {bits:2d}-bit {sr} Hz  {secs:6.2f}s  {"loop" if loop else "one-shot"}')
        count += 1
    print(f'{stem}: {count} samples')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out', default='Output/Samples')
    ap.add_argument('--rate', type=int, default=0, help='force a sample rate (default: per format)')
    args = ap.parse_args()
    files = []
    for p in args.inputs:
        if os.path.isdir(p):
            files += sorted(os.path.join(r, f) for r, _, fs in os.walk(p) for f in fs
                            if f.upper().endswith(('.S1M', '.S1A')))
        else:
            files.append(p)
    for f in files:
        try:
            export(f, args.out, args.rate)
        except ValueError as e:
            print(f'{f}: skipped: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
