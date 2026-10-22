import sys, struct
fn, want = sys.argv[1], [int(x,16) for x in sys.argv[2:]]
d = open(fn,'rb').read()
w = struct.unpack('>496H', d[0x20:0x400])
pos = 0x400; si = 0; ti = 0; shown = {}
for x in w:
    if x == 0x280: pos += 0x280; si += 1; ti = 0; continue
    if x:
        ph = d[pos:pos+x]
        if ph[:2] != b'\xf0\x00' or ph[-1] != 0xf2: print('BADFRAME sec', si, 'trk', ti, ph[:4].hex(), ph[-4:].hex())
        for i, b in enumerate(ph[2:-1], 2):
            if (b & 0x80) and (b >> 4) in want and shown.get(b>>4,0) < 4:
                shown[b>>4] = shown.get(b>>4,0)+1
                print(f'sec{si} trk{ti} op {b:02x}:', ph[max(0,i-12):i].hex(' '), '|', ph[i:i+12].hex(' '))
        pos += x
    ti += 1
