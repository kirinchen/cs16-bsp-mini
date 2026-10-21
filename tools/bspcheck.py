"""Structural sanity checks for a scaled GoldSrc BSP, compared against the original.

usage: python bspcheck.py original.bsp scaled.bsp [x y z ...]

Checks:
  * every lump index (planes, clipnodes, nodes, faces, texinfo, marksurfaces) is in range
  * clipnode ordering the engine enforces (no node index below its hull's head node)
  * every player spawn sits in empty space in the standing (hull 1) and crouching (hull 3) hulls
  * 40 units below every spawn is solid (i.e. there is a floor)
  * no spawn sits within 2 units of a wall (a spawn on a clip plane counts as stuck in-game)
  * collision matches the picture: 8 units in front of every visible wall face the standing and
    crouching hulls are solid (a player's half-width is 16, so an empty hull there lets him stand
    half inside the wall). This is the check that caught the clip-plane expansion sign bug.
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
    o, l = L[2]
    ntex = struct.unpack_from('<i', d, o)[0]
    offs = struct.unpack_from('<%di' % ntex, d, o + 4)
    B['texnames'] = [d[o + t:o + t + 16].split(b'\0')[0].decode('latin1').lower() if t > 0 else '' for t in offs]
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


def clearance(B, p, cap=8):
    """distance (capped) to the nearest wall in +-x / +-y for a standing player. A probe is a
    wall only if solid both at the origin height and 18 units higher, so ramps and steps next
    to the spot (which the engine walks up) do not count."""
    best = cap
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(1, cap + 1):
            q = (p[0] + dx * k, p[1] + dy * k, p[2])
            if contents(B, 1, q) != -1 and contents(B, 1, (q[0], q[1], q[2] + 18)) != -1:
                best = min(best, k - 1)
                break
    return best


def contents0(B, p):
    """point hull (the drawn geometry): leaf contents"""
    n = B['models'][0][9]
    while n >= 0:
        pl = B['planes'][B['nodes'][n][0]]
        n = B['nodes'][n][1] if pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2] - pl[3] >= 0 else B['nodes'][n][2]
    return B['leaves'][-1 - n][0]


TOOL_TEX = ('sky', 'aaatrigger', 'clip', 'origin', 'null', 'hint', 'skip', '{', '!')


def check_hull_walls(B, D=8.0):
    """world wall faces (|nz| <= 0.7, open air in front) where a player centre D units out is NOT
    solid in hull 1 or hull 3: returns (faces tested, list of offenders)"""
    m0 = B['models'][0]
    tested, bad = 0, []
    for fi in range(m0[14], m0[14] + m0[15]):
        f = B['faces'][fi]
        if B['texnames'][B['texinfo'][f[4]][8]].startswith(TOOL_TEX):
            continue
        nx, ny, nz, dist, _ = B['planes'][f[0]]
        if f[1]:
            nx, ny, nz = -nx, -ny, -nz
        if abs(nz) > 0.7:
            continue
        pts = []
        for k in range(f[2], f[2] + f[3]):
            e = B['surfedges'][k][0]
            pts.append(B['verts'][B['edges'][e][0] if e >= 0 else B['edges'][-e][1]])
        c = [sum(q[i] for q in pts) / len(pts) for i in range(3)]
        out = (c[0] + nx * D, c[1] + ny * D, c[2] + nz * D)
        if contents0(B, out) != -1:
            continue
        tested += 1
        if contents(B, 1, out) == -1 or contents(B, 3, out) == -1:
            bad.append((fi, tuple(round(x, 1) for x in c)))
    return tested, bad


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
        tight = [(p, clearance(B, p)) for p in sp if clearance(B, p) < 2]
        if tight:
            print(f"   {len(tight)} spawn(s) within 2 units of a wall (engine may treat as stuck): {tight}")
    for name, B in (("orig", A), ("scaled", M)):
        tested, bad = check_hull_walls(B)
        print(f"{name}: hull1/hull3 empty 8 units in front of a visible wall: {len(bad)} of {tested} faces"
              f"{'  OK' if not bad else '  PROBLEM (player can stand half inside the wall), e.g. ' + str(bad[:3])}")
    extra = [float(x) for x in sys.argv[3:]]
    for i in range(0, len(extra) - 2, 3):
        p = tuple(extra[i:i + 3])
        print("probe", p, "hull1", contents(M, 1, p), "hull3", contents(M, 3, p))


if __name__ == '__main__':
    main()
