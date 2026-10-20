"""Move one entity of a GoldSrc BSP by an offset, without touching geometry.

usage:
  python bspmove.py MAP.bsp ENT DX DY DZ [OUT.bsp]

ENT is the entity index (#n) as printed by the 3D viewer's locator, i.e. the n-th block
(0 = worldspawn) in the order `bspents.py MAP dump` prints them. The map is rewritten in place
unless OUT.bsp is given. Only that entity's "origin" key changes; every other byte of the
entity lump is kept. A brush entity without an "origin" key gets one equal to the offset,
which the engine applies to the whole brush model.
"""
import re
import sys

import bspents


def main():
    a = sys.argv[1:]
    if len(a) not in (5, 6):
        print(__doc__)
        sys.exit(1)
    src, n = a[0], int(a[1])
    dx, dy, dz = (float(v) for v in a[2:5])
    dst = a[5] if len(a) == 6 else src
    d, L, ents = bspents.read(src)
    spans = [m.span() for m in re.finditer(r'\{[^}]*\}', ents)]
    if not 0 <= n < len(spans):
        sys.exit('entity #%d out of range (map has %d)' % (n, len(spans)))
    s, e = spans[n]
    block = ents[s:e]
    k = bspents.kv(block)
    if n == 0:
        sys.exit('entity #0 is worldspawn; refusing to move it')
    old = k.get('origin')
    x, y, z = (float(v) for v in old.split()) if old else (0.0, 0.0, 0.0)
    new = '%g %g %g' % (x + dx, y + dy, z + dz)
    if old is not None:
        # replace the last "origin" pair (the one kv() and the engine use)
        ms = list(re.finditer(r'"origin" "[^"]*"', block))
        m = ms[-1]
        block = block[:m.start()] + '"origin" "%s"' % new + block[m.end():]
    else:
        block = block[:-1].rstrip('\n') + '\n"origin" "%s"\n}' % new
    bspents.write(dst, d, L, ents[:s] + block + ents[e:])
    print('%s#%d origin %s -> %s%s' % (k.get('classname', '?'), n, old or '(none)', new,
                                       '' if dst == src else '  written to ' + dst))


if __name__ == '__main__':
    main()
