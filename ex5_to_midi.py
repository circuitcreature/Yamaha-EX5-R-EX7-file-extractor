"""Export Yamaha EX5 patterns (.S1P files, or the pattern inside an .S1A
all-data file) to Standard MIDI Files.

For each input file, writes into <out>/<name>/:
  <name>_S01.mid ...   one type-1 MIDI file per section (8 tracks, phrases
                       looped to the section length)
  <name>_all.mid       every section back to back, with a marker per section

Usage: python3 ex5_to_midi.py FILE_OR_DIR ... [-o OUTDIR]
"""
import argparse
import os
import struct
import sys

import re

from ex5_pattern import BAR, TPQ, load_any


def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def track_chunk(events):
    """events: list of (tick, order, bytes). Returns an MTrk chunk."""
    events.sort(key=lambda e: (e[0], e[1]))
    body, last = bytearray(), 0
    end = max(e[0] for e in events)  # an empty payload only sets the end-of-track time
    for tick, _, data in events:
        if data:
            body += vlq(tick - last) + data
            last = tick
    body += vlq(end - last) + b'\xff\x2f\x00'
    return b'MTrk' + struct.pack('>I', len(body)) + bytes(body)


def meta(kind, payload):
    return bytes([0xFF, kind]) + vlq(len(payload)) + payload


def write_smf(path, tracks):
    with open(path, 'wb') as f:
        f.write(b'MThd' + struct.pack('>IHHH', 6, 1, len(tracks), TPQ))
        for t in tracks:
            f.write(track_chunk(t))


def looped(section, track, items):
    """Yield (tick, item) for phrase items repeated over the section."""
    ph = section.phrases[track]
    loop = section.track_bars[track] * BAR or ph.length or section.length
    for start in range(0, section.length, loop):
        for it in items:
            if it.tick >= loop:
                break
            t = start + it.tick
            if t >= section.length:
                break
            yield t, it


def section_notes(section, track):
    """Notes of one track, looped over the section. Yields (tick, note, vel, gate)."""
    ph = section.phrases[track]
    if ph is None:
        return
    for t, n in looped(section, track, ph.notes):
        yield t, n.note, n.vel, min(n.gate, section.length - t)


def section_events(section, track):
    """Controller / pitch bend / sysex events, looped. Yields (tick, data)."""
    ph = section.phrases[track]
    if ph is None:
        return
    for t, e in looped(section, track, ph.events):
        yield t, e.data


def tempo_event(tick, bpm):
    return (tick, 0, meta(0x51, struct.pack('>I', round(60_000_000 / bpm))[1:]))


def build(sections, label):
    """Build MIDI tracks for a list of sections placed end to end."""
    conductor = [(0, 0, meta(0x03, label.encode('latin-1', 'replace'))),
                 (0, 0, meta(0x58, bytes([4, 2, 24, 8])))]
    tracks = [[] for _ in range(8)]
    offset = 0
    for s in sections:
        conductor.append(tempo_event(offset, s.tempo))
        if len(sections) > 1:
            conductor.append((offset, 0, meta(0x06, section_label(s).encode('latin-1', 'replace'))))
        for t in range(8):
            ch = s.channels[t]
            for tick, note, vel, gate in section_notes(s, t):
                tracks[t].append((offset + tick, 1, bytes([0x90 | ch, note, max(1, vel)])))
                tracks[t].append((offset + tick + gate, 0, bytes([0x80 | ch, note, 0])))
            for tick, data in section_events(s, t):
                if data[0] == 0xF0:
                    msg = b'\xf0' + vlq(len(data) - 1) + data[1:]
                else:
                    msg = bytes([data[0] | ch]) + data[1:]
                tracks[t].append((offset + tick, 1, msg))
        offset += s.length
    conductor.append((offset, 0, b''))  # pins end-of-track to the end of the music
    out = [conductor]
    for t in range(8):
        if not tracks[t]:
            continue
        nums = sorted({s.phrases[t].number for s in sections if s.phrases[t] and s.phrases[t].number is not None})
        name = f'Track {t + 1}'
        if len(nums) == 1:
            name += f' (phrase {nums[0] + 1:03d})'
        out.append([(0, 0, meta(0x03, name.encode()))] + tracks[t])
    return out


def section_label(s):
    label = f'Section {s.index + 1:02d}'
    return label if s.name in ('', 'NewTrack') else f'{label} {s.name}'


def export(path, outdir):
    stem = os.path.splitext(os.path.basename(path))[0]
    pat, source = load_any(path)
    for w in pat.warnings:
        print(f'{stem}: warning: {w}')
    dest = os.path.join(outdir, stem)
    os.makedirs(dest, exist_ok=True)
    sections = [s for s in pat.sections if any(p and (p.notes or p.events) for p in s.phrases)]
    print(f'{stem} ({source}): {len(sections)} sections' + (f' ({len(pat.sections) - len(sections)} empty skipped)' if len(sections) < len(pat.sections) else ''))
    for s in sections:
        active = [t + 1 for t in range(8) if s.phrases[t] and (s.phrases[t].notes or s.phrases[t].events)]
        print(f'  S{s.index + 1:02d}  {s.name:8}  {s.bars:2d} bars  {s.tempo:g} BPM  tracks {active}')
        for t, ph in enumerate(s.phrases):
            for w in ph.warnings if ph else ():
                print(f'       warning: track {t + 1}: {w}')
        fname = f'{stem}_S{s.index + 1:02d}'
        if s.name not in ('', 'NewTrack'):
            fname += '_' + re.sub(r'[^A-Za-z0-9]+', '_', s.name).strip('_')
        write_smf(os.path.join(dest, fname + '.mid'), build([s], f'{stem} {section_label(s)}'))
    write_smf(os.path.join(dest, f'{stem}_all.mid'), build(sections, stem))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out', default='Output')
    args = ap.parse_args()
    files = []
    for p in args.inputs:
        if os.path.isdir(p):
            files += sorted(os.path.join(r, f) for r, _, fs in os.walk(p) for f in fs if f.upper().endswith(('.S1P', '.S1A')))
        else:
            files.append(p)
    for f in files:
        try:
            export(f, args.out)
        except ValueError as e:
            print(f'{f}: skipped: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
