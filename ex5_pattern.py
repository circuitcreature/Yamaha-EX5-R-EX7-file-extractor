"""Parser for Yamaha EX5 pattern files (.S1P, header 'SY1200PTN  V1.00').

File layout (all big-endian):
  0x000  16-byte magic 'SY1200PTN  V1.00', zero padding to 0x20
  0x020  length table, 496 u16 words = 55 fixed slots of 9 words, one per
         section number: 8 phrase byte lengths (one per track, 0 = empty)
         followed by 0x0280 (the size of the section parameter block).
         An unused section slot is all zeros.
  0x400  data: for each section, its non-empty phrases in track order,
         then the 0x280-byte parameter block.

Phrase stream: f0 00 <events> f2
  80-9F            delta time, b & 0x1F ticks
  A0-BF xx         delta time, (b & 0x1F) << 7 | xx
  D0-DF gg nn vv   note: gate (b & 0x0F) << 7 | gg, note nn, velocity vv
  C0-CF nn vv      note with short gate b & 0x0F
  E0-EF g1 g2 nn vv  note with long gate (b & 0x0F) << 14 | g1 << 7 | g2
  F6 ... F7        system exclusive message (F6 stands in for F0)
  FB cc vv         control change
  FE ll mm         pitch bend, 14-bit (ll = LSB, mm = MSB)
  F3 x5, FC x4     unidentified, skipped (seen in factory patterns)
Resolution is 480 ticks per quarter note.

Parameter block (offsets relative to block start):
  0x00  8-byte name ('NewTrack')
  0x08  u16 tempo * 10
  0x0D  section length in bars
  0x0F  8 x 4 bytes per-track info; byte 1 = phrase length in bars
  0xB0  8 bytes, low nibble = MIDI channel per track (0x70..0x77)
  0xB8  groove template name ('USER TMPL')
  0x247 8 x u16 phrase number per track (0xfefe = none)
"""
import struct

TPQ = 480
BAR = TPQ * 4
PARAM_SIZE = 0x280
MAGIC = b'SY1200PTN'


class Note:
    __slots__ = ('tick', 'note', 'vel', 'gate')

    def __init__(self, tick, note, vel, gate):
        self.tick, self.note, self.vel, self.gate = tick, note, vel, gate


class Event:
    """A non-note MIDI event; data is a channel message without its
    status channel (b0/e0 status byte included), or a full f0..f7 sysex."""
    __slots__ = ('tick', 'data')

    def __init__(self, tick, data):
        self.tick, self.data = tick, data


# Opcodes not yet identified, with their data byte counts.
SKIPPED = {0xF3: 5, 0xFC: 4}


class Phrase:
    def __init__(self, raw, number=None):
        self.raw = raw
        self.number = number
        self.warnings = []
        self.events = []
        self.notes, self.length = self._decode(raw)

    def _decode(self, raw):
        if not (raw[:2] == b'\xf0\x00' and raw[-1] == 0xf2):
            # Damaged slot: salvage the last well-formed phrase inside it.
            start = raw.rfind(b'\xf0\x00')
            self.warnings.append(
                f'malformed phrase ({len(raw)} bytes); salvaged {len(raw) - start if start >= 0 else 0} bytes at tail')
            if start < 0 or raw[-1] != 0xf2:
                return [], 0
            raw = raw[start:]
        notes, tick, i, end = [], 0, 2, len(raw) - 1
        while i < end:
            b = raw[i]
            if 0x80 <= b <= 0x9F:
                tick += b & 0x1F
                i += 1
            elif 0xA0 <= b <= 0xBF:
                tick += ((b & 0x1F) << 7) | raw[i + 1]
                i += 2
            elif 0xC0 <= b <= 0xCF:
                notes.append(Note(tick, raw[i + 1], raw[i + 2], b & 0x0F))
                i += 3
            elif 0xD0 <= b <= 0xDF:
                gate = ((b & 0x0F) << 7) | raw[i + 1]
                notes.append(Note(tick, raw[i + 2], raw[i + 3], gate))
                i += 4
            elif 0xE0 <= b <= 0xEF:
                gate = ((b & 0x0F) << 14) | (raw[i + 1] << 7) | raw[i + 2]
                notes.append(Note(tick, raw[i + 3], raw[i + 4], gate))
                i += 5
            elif b == 0xFB:
                self.events.append(Event(tick, bytes([0xB0, raw[i + 1], raw[i + 2]])))
                i += 3
            elif b == 0xFE:
                self.events.append(Event(tick, bytes([0xE0, raw[i + 1], raw[i + 2]])))
                i += 3
            elif b == 0xF6:
                stop = raw.index(0xF7, i)
                self.events.append(Event(tick, b'\xf0' + raw[i + 1:stop + 1]))
                i = stop + 1
            elif b in SKIPPED:
                self.skipped = getattr(self, 'skipped', 0) + 1
                i += 1 + SKIPPED[b]
            else:
                self.warnings.append(f'unknown byte {b:02x} at offset {i}; rest of phrase skipped')
                break
        return notes, tick


class Section:
    def __init__(self, index, phrases, param):
        self.index = index
        self.phrases = phrases          # list of 8 (Phrase or None)
        self.param = param
        self.name = param[0:8].rstrip(b'\0 ').decode('latin-1')
        self.tempo = struct.unpack('>H', param[8:10])[0] / 10
        self.bars = param[0x0D]
        self.track_bars = [param[0x0F + 4 * t + 1] for t in range(8)]
        self.channels = [b & 0x0F for b in param[0xB0:0xB8]]
        nums = struct.unpack('>8H', param[0x247:0x257])
        for p, n in zip(phrases, nums):
            if p is not None and n != 0xFEFE:
                p.number = n

    @property
    def length(self):
        return self.bars * BAR


class Pattern:
    def __init__(self, data, table=0x20, start=0x400, nslots=55, exact=True):
        if exact and not data.startswith(MAGIC):
            raise ValueError('not an EX5 pattern file (bad magic)')
        words = struct.unpack(f'>{nslots * 9}H', data[table:table + nslots * 18])
        self.sections, self.warnings, pos = [], [], start
        # Fixed 9-word slots per section number; an unused slot is all zeros.
        for slot in range(nslots):
            *lens, size = words[slot * 9:slot * 9 + 9]
            if size != PARAM_SIZE:
                if size or any(lens):
                    if exact:
                        raise ValueError(f'section slot {slot + 1}: unexpected table entry')
                    self.warnings.append(f'section slot {slot + 1}: stray table entry ignored')
                continue
            phrases = []
            for n in lens:
                phrases.append(Phrase(data[pos:pos + n]) if n else None)
                pos += n
            self.sections.append(Section(slot, phrases, data[pos:pos + PARAM_SIZE]))
            pos += PARAM_SIZE
        self.end = pos
        if exact and pos != len(data):
            raise ValueError(f'data ends at {pos:#x} but file is {len(data):#x} bytes')

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            return cls(f.read())


def load_any(path):
    """Load the pattern from a .S1P file, or the one embedded in the SEQ block
    of an .S1A all-data file. Returns (Pattern, source description)."""
    with open(path, 'rb') as f:
        data = f.read()
    if data.startswith(MAGIC):
        return Pattern(data), 'pattern file'
    if data.startswith(b'SY1200ALL'):
        seq = data.find(b'SY1200SEQ')
        if seq < 0:
            raise ValueError('all-data file has no SEQ block')
        # SEQ block: song header, then a pattern table at +0x480 (53 slots)
        # and phrase data at +0x840. Offsets taken from one sample file.
        return Pattern(data[seq:], table=0x480, start=0x840, nslots=53, exact=False), 'SEQ block of all-data file'
    raise ValueError('not an EX5 pattern or all-data file')
