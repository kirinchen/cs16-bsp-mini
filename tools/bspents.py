"""Edit the entity lump of a GoldSrc BSP without touching geometry.

usage:
  python bspents.py MAP.bsp dump [classname]
      print entities (optionally only one class)
  python bspents.py IN.bsp OUT.bsp line CLASS X Z Y0 Y1
      re-space every entity of CLASS along a line: x = X, z = Z, y evenly from Y0 to Y1
      (keeps their other keys such as angle). Use it when spawn points end up closer than
      64 units after scaling: CS refuses a spawn with another player within 64 units and
      stacks players on top of each other once every spot is "occupied".
"""
import struct
import sys
import re


def read(path):
    d = open(path, 'rb').read()
    L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]
    o, l = L[0]
    ents = d[o:o + l].split(b'\0')[0].decode('latin1')
    return d, L, ents


def write(path, d, L, ents):
    lumps = {i: d[L[i][0]:L[i][0] + L[i][1]] for i in range(15)}
    lumps[0] = ents.encode('latin1') + b'\0'
    order = sorted(range(15), key=lambda i: L[i][0])
    body = bytearray()
    hdr = [None] * 15
    pos = 4 + 8 * 15
    for i in order:
        while (pos + len(body)) % 4:
            body.append(0)
        hdr[i] = (pos + len(body), len(lumps[i]))
        body += lumps[i]
    open(path, 'wb').write(struct.pack('<i', 30) + b''.join(struct.pack('<ii', *h) for h in hdr) + bytes(body))


def blocks(ents):
    return re.findall(r'\{[^}]*\}', ents)


def kv(block):
    return dict(re.findall(r'"([^"]*)" "([^"]*)"', block))


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[1] == 'dump':
        d, L, ents = read(a[0])
        want = a[2] if len(a) > 2 else None
        for b in blocks(ents):
            k = kv(b)
            if want is None or k.get('classname') == want:
                print(k)
        return
    if len(a) >= 8 and a[2] == 'line':
        src, dst, _, cls = a[:4]
        x, z, y0, y1 = (float(v) for v in a[4:8])
        d, L, ents = read(src)
        out = []
        idx = 0
        n = sum(1 for b in blocks(ents) if kv(b).get('classname') == cls)
        for b in blocks(ents):
            k = kv(b)
            if k.get('classname') == cls:
                y = y0 + (y1 - y0) * idx / max(n - 1, 1)
                k['origin'] = '%g %g %g' % (x, y, z)
                idx += 1
                b = '{\n' + '\n'.join('"%s" "%s"' % (kk, vv) for kk, vv in k.items()) + '\n}'
            out.append(b)
        write(dst, d, L, '\n'.join(out) + '\n')
        print("re-spaced", n, cls, "along x=%g z=%g, y %g..%g, spacing %.1f" % (x, z, y0, y1, (y1 - y0) / max(n - 1, 1)))
        return
    print(__doc__)


if __name__ == '__main__':
    main()
