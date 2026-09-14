"""Structural sanity checks for a scaled GoldSrc BSP, compared against the original.

usage: python bspcheck.py original.bsp scaled.bsp [x y z ...]

Checks:
  * every lump index (planes, clipnodes, nodes, faces, texinfo, marksurfaces) is in range
  * clipnode ordering the engine enforces (no node index below its hull's head node)
  * every player spawn sits in empty space in the standing (hull 1) and crouching (hull 3) hulls
  * 40 units below every spawn is solid (i.e. there is a floor)
Optional: extra "x y z" triples are probed in hull 1 / hull 3 of the scaled map and their
contents printed (-1 empty, -2 solid, -3 water).
"""
import struct
import sys
import re


def load(path):
    d = open(path, 'rb').read()
    L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]

    def arr(i, fmt):
        sz = struct.calcsize(fmt)
        o, l = L[i]
        return [struct.unpack_from(fmt, d, o + sz * k) for k in range(l // sz)]
    B = {
        'planes': arr(1, '<3ffi'), 'clip': arr(9, '<ihh'), 'models': arr(14, '<3f3f3f4iiii'),
        'nodes': arr(5, '<ihh3h3hHH'), 'leaves': arr(10, '<ii3h3hHH4B'), 'faces': arr(7, '<HHiHH4Bi'),
        'texinfo': arr(6, '<8fii'), 'verts': arr(3, '<3f'), 'edges': arr(12, '<HH'),
        'surfedges': arr(13, '<i'), 'marks': arr(11, '<H'),
    }
    o, l = L[0]
    B['ents'] = d[o:o + l].decode('latin1')
    return B


def contents(B, hull, p, model=0):
    n = B['models'][model][9 + hull]
    while n >= 0:
        pl = B['planes'][B['clip'][n][0]]
        dist = pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2] - pl[3]
        n = B['clip'][n][1] if dist >= 0 else B['clip'][n][2]
    return n


def check_indices(B):
    np_, nc, nn, nf, nt, ns, nm = (len(B[k]) for k in ('planes', 'clip', 'nodes', 'faces', 'texinfo', 'surfedges', 'marks'))
    bad = 0
    for c in B['clip']:
        bad += not (0 <= c[0] < np_) or c[1] >= nc or c[2] >= nc
    for n in B['nodes']:
        bad += not (0 <= n[0] < np_) or n[1] >= nn or n[2] >= nn or n[9] + n[10] > nf
    for f in B['faces']:
        bad += f[0] >= np_ or f[4] >= nt or f[2] + f[3] > ns
    for l in B['leaves']:
        bad += l[8] + l[9] > nm
    for m in B['models']:
        bad += m[9] >= nn or any(m[9 + h] >= nc for h in (1, 2, 3)) or m[14] + m[15] > nf
    return bad


def check_clip_order(B):
    """engine rule (PM_HullPointContents): every node reachable from a hull's head node must have
    an index >= that head node"""
    bad = 0
    for m in B['models']:
        for h in (1, 2, 3):
            root = m[9 + h]
            seen = set()
            stack = [root]
            while stack:
                i = stack.pop()
                if i < 0 or i in seen:
                    continue
                seen.add(i)
                if i < root:
                    bad += 1
                stack.extend(B['clip'][i][1:3])
    return bad


def spawns(B):
    out = []
    for blk in re.findall(r'\{([^}]*)\}', B['ents']):
        kv = dict(re.findall(r'"([^"]*)" "([^"]*)"', blk))
        if kv.get('classname') in ('info_player_start', 'info_player_deathmatch') and 'origin' in kv:
            out.append(tuple(float(t) for t in kv['origin'].split()))
    return out


def main():
    A = load(sys.argv[1])
    M = load(sys.argv[2])
    print("index errors: orig", check_indices(A), "scaled", check_indices(M))
    print("clipnode order errors: orig", check_clip_order(A), "scaled", check_clip_order(M))
    for name, B in (("orig", A), ("scaled", M)):
        sp = spawns(B)
        h1 = {contents(B, 1, p) for p in sp}
        h3 = {contents(B, 3, p) for p in sp}
        below = {contents(B, 1, (p[0], p[1], p[2] - 40)) for p in sp}
        ok = h1 == {-1} and h3 == {-1} and below == {-2}
        print(f"{name}: {len(sp)} spawns  hull1={h1} hull3={h3} floor-below={below}  {'OK' if ok else 'PROBLEM'}")
    extra = [float(x) for x in sys.argv[3:]]
    for i in range(0, len(extra) - 2, 3):
        p = tuple(extra[i:i + 3])
        print("probe", p, "hull1", contents(M, 1, p), "hull3", contents(M, 3, p))


if __name__ == '__main__':
    main()
