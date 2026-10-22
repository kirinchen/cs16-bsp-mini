"""Bring the original map's player clipping back into a recompiled BSP.

A decompile only sees hull 0, so CLIP brushes (which exist only in the player hulls 1-3) are lost
and a recompiled map lets players walk where the mapper had blocked them. This tool makes each
player hull of NEW the union of NEW's hull and ORIG's hull, except inside MASK: a set of convex
volumes (unexpanded, in map units) where the edit deliberately opened space, e.g. a lifted sky.
The mask is expanded by each hull's half-size before use.

Tree union: every empty leaf of NEW's hull tree is pointed at a mask test (a kd-split over the mask
volumes, each a chain of planes); inside any volume -> empty, outside all -> ORIG's hull tree.
Subtrees are shared, all new clipnodes are appended after the existing ones (so the engine rule
"node index >= head node" holds) and the 32767-clipnode limit is checked.

usage: python bspclipmerge.py NEW.bsp ORIG.bsp OUT.bsp [MASK.json] [--hulls=1,3]
MASK.json is either a list of convex volumes, [[[nx, ny, nz, d], ...], ...] (outward half-spaces
n.x <= d), or a heightfield {"grid", "x0", "y0", "nx", "ny", "lo": [[...]], "hi": [[...]]}: per cell
the original clipping above some z in [lo, hi] is dropped (+-99999 = unconstrained). A kd split over
the cells keeps that to a few thousand clipnodes; a leaf is split until its cells' lo values are
within --tol (default 64) of each other, so one high cell does not keep clip over a whole street. --hulls limits the merge (CS players only use 1 and 3).
"""
import json
import struct
import sys

HULLS = {1: (16, 16, 36), 2: (32, 32, 32), 3: (16, 16, 18)}
INF = 99999


def read(path):
    d = open(path, 'rb').read()
    L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]
    return d, L


def arr(d, L, i, fmt):
    sz = struct.calcsize(fmt)
    o, l = L[i]
    return [list(struct.unpack_from(fmt, d, o + sz * k)) for k in range(l // sz)]


def write(path, d, L, repl):
    lumps = {i: repl.get(i, d[L[i][0]:L[i][0] + L[i][1]]) for i in range(15)}
    body = bytearray(d[:4] + b'\0' * 120)
    hdr = []
    for i in range(15):
        while len(body) % 4:
            body += b'\0'
        hdr.append((len(body), len(lumps[i])))
        body += lumps[i]
    for i, (o, l) in enumerate(hdr):
        struct.pack_into('<ii', body, 4 + 8 * i, o, l)
    open(path, 'wb').write(bytes(body))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opts = [a for a in sys.argv[1:] if a.startswith('--')]
    new_p, orig_p, out_p = args[:3]
    mask = json.load(open(args[3])) if len(args) > 3 else []
    hfd = mask if isinstance(mask, dict) else None
    if hfd:
        LO, HI, mask = hfd['lo'], hfd['hi'], []
    TOL = float(next((a[6:] for a in opts if a.startswith('--tol=')), 64))
    hulls = [int(h) for a in opts if a.startswith('--hulls=') for h in a[8:].split(',')] or [1, 2, 3]
    d, L = read(new_p)
    od, oL = read(orig_p)
    planes = arr(d, L, 1, '<3ffi')
    clip = arr(d, L, 9, '<ihh')
    models = arr(d, L, 14, '<3f3f3f4iiii')
    oplanes = arr(od, oL, 1, '<3ffi')
    oclip = arr(od, oL, 9, '<ihh')
    omodels = arr(od, oL, 14, '<3f3f3f4iiii')
    pindex = {}
    for i, p in enumerate(planes):
        pindex[(round(p[0], 5), round(p[1], 5), round(p[2], 5), round(p[3], 3))] = i

    def add_plane(n, dist):
        """canonical plane index and whether the caller must swap front/back"""
        n = list(n)
        flip = False
        ax = max(range(3), key=lambda k: abs(n[k]))
        if abs(n[ax]) > 0.99999 and n[ax] < 0:      # axial planes must face +axis (engine: p[type] - dist)
            n, dist, flip = [-v for v in n], -dist, True
        key = (round(n[0], 5), round(n[1], 5), round(n[2], 5), round(dist, 3))
        if key not in pindex:
            if abs(n[0]) > 0.99999:
                t = 0
            elif abs(n[1]) > 0.99999:
                t = 1
            elif abs(n[2]) > 0.99999:
                t = 2
            else:
                t = 3 + max(range(3), key=lambda k: abs(n[k]))
            pindex[key] = len(planes)
            planes.append([n[0], n[1], n[2], dist, t])
        return pindex[key], flip

    def node(n, dist, front, back):
        pi, flip = add_plane(n, dist)
        if flip:
            front, back = back, front
        clip.append([pi, front, back])
        return len(clip) - 1

    stats = {}
    n_new = len(clip)              # only NEW's own nodes are grafted; appended ones are left alone
    for h in hulls:
        e = HULLS[h]
        # ---- ORIG hull tree, copied (planes remapped), appended ----
        omap = {}

        def copy_orig(i):
            if i < 0:
                return i
            if i in omap:
                return omap[i]
            stack = [i]
            order, inorder = [], set()
            while stack:
                k = stack.pop()
                if k < 0 or k in omap or k in inorder:
                    continue
                order.append(k)
                inorder.add(k)
                stack.extend((oclip[k][1], oclip[k][2]))
            for k in order:                  # reserve indices in pre-order
                omap[k] = len(clip)
                clip.append(None)
            for k in order:
                p = oplanes[oclip[k][0]]
                pi, flip = add_plane(p[:3], p[3])
                assert not flip
                f, b = oclip[k][1], oclip[k][2]
                clip[omap[k]] = [pi, omap.get(f, f) if f >= 0 else f, omap.get(b, b) if b >= 0 else b]
            return omap[i]
        orig_root = copy_orig(omodels[0][9 + h])

        # ---- mask volumes expanded by the hull ----
        vols = []
        for v in mask:
            hs = []
            for nx, ny, nz, dist in v:
                hs.append(((nx, ny, nz), dist + abs(nx) * e[0] + abs(ny) * e[1] + abs(nz) * e[2] + 0.5))
            vols.append(hs)

        def bounds(hs):
            lo, hi = [-1e9] * 3, [1e9] * 3
            for n, dist in hs:
                for k in range(3):
                    if abs(n[k]) > 0.99999:
                        if n[k] > 0:
                            hi[k] = min(hi[k], dist)
                        else:
                            lo[k] = max(lo[k], -dist)
            return lo, hi
        vb = [bounds(hs) for hs in vols]

        def chain(idx, outside):
            """volumes idx tested in turn; inside one -> empty (-1), outside all -> `outside`"""
            nxt = outside
            for i in reversed(idx):
                head = -1
                for n, dist in reversed(vols[i]):
                    head = node(n, dist, nxt, head)    # front (n.x > dist) is outside this volume
                nxt = head
            return nxt

        def kd(idx, depth=0):
            if len(idx) <= 3 or depth > 24:
                return chain(idx, orig_root)
            spans = [(max(vb[i][1][k] for i in idx) - min(vb[i][0][k] for i in idx), k) for k in (0, 1)]
            ax = max(spans)[1]
            cs = sorted((vb[i][0][ax] + vb[i][1][ax]) / 2 for i in idx)
            c = cs[len(cs) // 2]
            left = [i for i in idx if vb[i][0][ax] < c]
            right = [i for i in idx if vb[i][1][ax] > c]
            if len(left) == len(idx) or len(right) == len(idx):
                return chain(idx, orig_root)
            n = [0.0, 0.0, 0.0]
            n[ax] = 1.0
            r = kd(right, depth + 1)
            lft = kd(left, depth + 1)
            return node(n, c, r, lft)
        def hf(i0, i1, j0, j1):
            """heightfield mask: kd split over cells until one z covers every cell's [lo, hi]"""
            los = [LO[j][i] for j in range(j0, j1) for i in range(i0, i1)]
            lo, hi = max(los), min(HI[j][i] for j in range(j0, j1) for i in range(i0, i1))
            fl = [v for v in los if v > -INF]
            if (lo <= hi and (not fl or max(fl) - min(fl) <= TOL)) or (i1 - i0 == 1 and j1 - j0 == 1):
                v = lo if lo > -INF else hi      # lowest allowed: drops the most clip
                if v >= INF or v <= -INF:
                    return orig_root
                return node((0.0, 0.0, 1.0), v - e[2], -1, orig_root)   # above: original clip dropped
            if i1 - i0 >= j1 - j0:
                m = (i0 + i1) // 2
                r, lft = hf(m, i1, j0, j1), hf(i0, m, j0, j1)
                return node((1.0, 0.0, 0.0), hfd['x0'] + m * hfd['grid'], r, lft)
            m = (j0 + j1) // 2
            r, lft = hf(i0, i1, m, j1), hf(i0, i1, j0, m)
            return node((0.0, 1.0, 0.0), hfd['y0'] + m * hfd['grid'], r, lft)

        if hfd:
            mask_root = hf(0, hfd['nx'], 0, hfd['ny'])
        else:
            mask_root = kd(list(range(len(vols)))) if vols else orig_root

        # ---- graft: every empty leaf of NEW's hull -> mask test ----
        head = models[0][9 + h]
        seen, stack, grafted = set(), [head], 0
        while stack:
            k = stack.pop()
            if k < 0 or k >= n_new or k in seen:
                continue
            seen.add(k)
            for s in (1, 2):
                c = clip[k][s]
                if c == -1:
                    clip[k][s] = mask_root
                    grafted += 1
                elif c >= 0:
                    stack.append(c)
        stats[h] = grafted
    assert len(clip) <= 32767, "too many clipnodes: %d" % len(clip)
    assert len(planes) <= 32767, "too many planes: %d" % len(planes)
    repl = {1: b''.join(struct.pack('<3ffi', *p) for p in planes),
            9: b''.join(struct.pack('<ihh', *c) for c in clip)}
    write(out_p, d, L, repl)
    print('clipnodes', len(clip), 'planes', len(planes), 'empty leaves grafted per hull', stats, '->', out_p)


if __name__ == '__main__':
    main()
