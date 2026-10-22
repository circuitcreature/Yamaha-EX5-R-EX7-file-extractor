import sys, struct, collections
def table(d):
    w = struct.unpack('>496H', d[0x20:0x400])
    secs, cur = [], []
    for x in w:
        if x == 0x280:
            secs.append(cur); cur = []
        else:
            cur.append(x)
    return secs, cur
for fn in sys.argv[1:]:
    d = open(fn,'rb').read()
    secs, rest = table(d)
    pos = 0x400; ops = collections.Counter(); ok = True
    for s in secs:
        if len(s) != 8: ok = False
        for L in s:
            if L:
                ph = d[pos:pos+L]
                if ph[:2] != b'\xf0\x00' or ph[-1] != 0xf2: ok = False
                for b in ph[2:-1]:
                    if b & 0x80: ops[b >> 4] += 1
                pos += L
        pos += 0x280
    print(fn, 'sections', len(secs), 'ok', ok, 'end', hex(pos), 'size', hex(len(d)), 'rest', [hex(x) for x in rest if x][:8], {hex(k): v for k, v in sorted(ops.items())})
