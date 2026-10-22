"""General GoldSrc BSP -> Valve-220 .map decompiler (any plane orientation).

Every leaf of a model's hull-0 node tree is a convex region: the intersection of the half-spaces
on the path from the root. Solid leaves (and sky leaves of the world) are written out as one brush
each, so slanted brushes, ramps and bevelled pillars survive. A brush face that lies on a drawn
BSP face gets that face's texture and texture axes (largest overlap wins); faces nobody could see
get NULL. Brush entities (*N models) are decompiled the same way into their own entity.

What is lost: CLIP / player-clip brushes (they only exist in hulls 1-3), origin brushes, hint /
skip, and the exact brush split the mapper used. Run sdHLT on the result to get a new BSP.

usage: python bsp2map.py MAP.bsp OUT.map [wadlist]
   or import: brushes, ents, B = decompile_all('map.bsp')   # brushes: {model index: [brush,...]}
              brush = {'contents': -2 | -6, 'faces': [(normal, point, texinfo), ...], 'polys': [...]}
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bspdecomp import load, face_pts, write_map  # noqa: E402

EPS = 0.01
MIN_THICK = 0.5     # thinner leaves are float slivers between near-parallel planes; hlcsg cannot rebuild them


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def clip_poly(poly, n, d, keep_front):
    """keep the part of a convex polygon with n.x >= d (keep_front) or <= d"""
    out = []
    k = len(poly)
    for i in range(k):
        a, b = poly[i], poly[(i + 1) % k]
        da, db = dot(n, a) - d, dot(n, b) - d
        if not keep_front:
            da, db = -da, -db
        if da >= -EPS:
            out.append(a)
        if (da > EPS and db < -EPS) or (da < -EPS and db > EPS):
            t = da / (da - db)
            out.append(tuple(a[j] + t * (b[j] - a[j]) for j in range(3)))
    return out


def poly_area(poly):
    if len(poly) < 3:
        return 0.0
    s = [0.0, 0.0, 0.0]
    for i in range(1, len(poly) - 1):
        u = [poly[i][j] - poly[0][j] for j in range(3)]
        v = [poly[i + 1][j] - poly[0][j] for j in range(3)]
        s[0] += u[1] * v[2] - u[2] * v[1]
        s[1] += u[2] * v[0] - u[0] * v[2]
        s[2] += u[0] * v[1] - u[1] * v[0]
    return 0.5 * math.sqrt(dot(s, s))


def order_cap(pts, n):
    uniq = []
    for q in pts:
        if not any(abs(q[0] - r[0]) + abs(q[1] - r[1]) + abs(q[2] - r[2]) < 1e-3 for r in uniq):
            uniq.append(q)
    if len(uniq) < 3:
        return []
    c = tuple(sum(q[k] for q in uniq) / len(uniq) for k in range(3))
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = (n[1] * a[2] - n[2] * a[1], n[2] * a[0] - n[0] * a[2], n[0] * a[1] - n[1] * a[0])
    v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
    uniq.sort(key=lambda q: math.atan2(dot(v, (q[0] - c[0], q[1] - c[1], q[2] - c[2])),
                                       dot(u, (q[0] - c[0], q[1] - c[1], q[2] - c[2]))))
    return uniq


def split(faces, n, d, keep_front, tag):
    """faces: list of (outward normal, d, polygon, tag). Clip a convex polytope by a plane."""
    out, on = [], []
    for fn, fd, poly, ft in faces:
        g = clip_poly(poly, n, d, keep_front)
        if len(g) >= 3 and poly_area(g) > 1e-4:
            out.append((fn, fd, g, ft))
            on.extend(q for q in g if abs(dot(n, q) - d) < 2 * EPS)
    on_n = (-n[0], -n[1], -n[2]) if keep_front else n       # outward normal of the new cap
    cap = order_cap(on, on_n)
    cap_d = -d if keep_front else d
    if any(dot(fn, on_n) > 0.9999 and abs(fd - cap_d) < 2 * EPS for fn, fd, _, _ in out):
        return out                     # the cut runs along an existing face: no new face
    if len(cap) >= 3 and poly_area(cap) > 1e-4:
        out.append((on_n, -d if keep_front else d, cap, tag))
    return out


def box(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    spec = [((0, 0, -1), -z0, (0, 3, 2, 1)), ((0, 0, 1), z1, (4, 5, 6, 7)), ((0, -1, 0), -y0, (0, 1, 5, 4)),
            ((0, 1, 0), y1, (2, 3, 7, 6)), ((1, 0, 0), x1, (1, 2, 6, 5)), ((-1, 0, 0), -x0, (0, 4, 7, 3))]
    return [(n, d, [P[i] for i in idx], None) for n, d, idx in spec]


def extent(faces):
    """thickness of a convex polytope: over its faces, the smallest depth of the solid behind the face"""
    pts = [q for f in faces for q in f[2]]
    if not pts:
        return 0.0
    return min(max(d - dot(n, q) for q in pts) for n, d, _, _ in faces)


def leaf_regions(B, head, lo, hi, want):
    """yield (contents, faces) for every leaf under node `head` whose contents is in `want`"""
    planes, nodes, leaves = B['planes'], B['nodes'], B['leaves']
    stack = [(head, box(lo, hi))]
    while stack:
        n, faces = stack.pop()
        if n < 0:
            c = leaves[-1 - n][0]
            if c in want and len(faces) >= 4 and extent(faces) > MIN_THICK:
                yield c, faces
            continue
        pi = nodes[n][0]
        p = planes[pi]
        nn, d = (p[0], p[1], p[2]), p[3]
        f = split(faces, nn, d, True, (pi, -1))
        if len(f) >= 4:
            stack.append((nodes[n][1], f))
        b = split(faces, nn, d, False, (pi, 1))
        if len(b) >= 4:
            stack.append((nodes[n][2], b))


def _proj(poly, n):
    ax = max(range(3), key=lambda i: abs(n[i]))
    i, j = [k for k in range(3) if k != ax]
    return [(q[i], q[j]) for q in poly]


def _area2(p):
    return 0.5 * sum(p[k][0] * p[(k + 1) % len(p)][1] - p[(k + 1) % len(p)][0] * p[k][1] for k in range(len(p)))


def overlap(a, b, n):
    """area of the intersection of two convex coplanar polygons (projected)"""
    A, C = _proj(a, n), _proj(b, n)
    if _area2(A) < 0:
        A = A[::-1]
    if _area2(C) < 0:
        C = C[::-1]
    out = A
    for k in range(len(C)):
        if len(out) < 3:
            return 0.0
        p, q = C[k], C[(k + 1) % len(C)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        inp, nxt = out, []
        for m in range(len(inp)):
            s, e = inp[m], inp[(m + 1) % len(inp)]
            cs = ex * (s[1] - p[1]) - ey * (s[0] - p[0])
            ce = ex * (e[1] - p[1]) - ey * (e[0] - p[0])
            if cs >= -1e-6:
                nxt.append(s)
            if (cs > 1e-6 and ce < -1e-6) or (cs < -1e-6 and ce > 1e-6):
                t = cs / (cs - ce)
                nxt.append((s[0] + t * (e[0] - s[0]), s[1] + t * (e[1] - s[1])))
        out = nxt
    return abs(_area2(out)) if len(out) >= 3 else 0.0


def drawn_faces(B, mi):
    """{(plane index, outward sign): [(polygon, texinfo)]} for the faces of model mi"""
    m = B['models'][mi]
    out = {}
    for f in B['faces'][m[14]:m[14] + m[15]]:
        ti = B['texinfo'][f[4]]
        sign = 1 if f[1] == 0 else -1
        out.setdefault((f[0], sign), []).append((face_pts(B, f), (B['texnames'][ti[8]], ti[0:4], ti[4:8])))
    return out


def decompile_model(B, mi, margin=16):
    m = B['models'][mi]
    lo = [m[k] - margin for k in range(3)]
    hi = [m[3 + k] + margin for k in range(3)]
    want = (-2, -6) if mi == 0 else (-2,)
    drawn = drawn_faces(B, mi)

    def cover(n, poly, tag):
        """{texinfo: overlap area} of the drawn faces under one brush face"""
        acc = {}
        if tag is not None:
            for dp, dti in drawn.get(tag, ()):
                a = overlap(poly, dp, n)
                if a > 1e-3:
                    acc[dti] = acc.get(dti, 0.0) + a
        return acc

    def cutter(faces):
        """an edge plane of a drawn face that separates two textures on one brush face, or None"""
        for n, d, poly, tag in faces:
            acc = cover(n, poly, tag)
            if len(acc) < 2:
                continue
            main = max(acc, key=acc.get)
            for dp, dti in drawn.get(tag, ()):
                if dti == main or overlap(poly, dp, n) <= 1e-3:
                    continue
                for k in range(len(dp)):
                    a, b = dp[k], dp[(k + 1) % len(dp)]
                    e = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
                    cn = (n[1] * e[2] - n[2] * e[1], n[2] * e[0] - n[0] * e[2], n[0] * e[1] - n[1] * e[0])
                    ln = math.sqrt(dot(cn, cn))
                    if ln < 1e-6:
                        continue
                    cn = (cn[0] / ln, cn[1] / ln, cn[2] / ln)
                    cd = dot(cn, a)
                    pts = [q for f in faces for q in f[2]]
                    if max(dot(cn, q) - cd for q in pts) > MIN_THICK and min(dot(cn, q) - cd for q in pts) < -MIN_THICK:
                        return cn, cd
        return None

    brushes = []
    for c, faces in leaf_regions(B, m[9], lo, hi, want):
        todo = [(faces, 0)]
        while todo:
            faces, depth = todo.pop()
            cut = cutter(faces) if c != -6 and depth < 16 else None
            if cut:
                for keep in (True, False):
                    g = split(faces, cut[0], cut[1], keep, None)
                    if len(g) >= 4 and extent(g) > MIN_THICK:
                        todo.append((g, depth + 1))
                continue
            out = []
            for n, d, poly, tag in faces:
                ti = None
                if c == -6:
                    ti = ('sky', None, None)
                else:
                    acc = cover(n, poly, tag)
                    if acc:
                        ti = max(acc, key=acc.get)
                out.append((n, poly[0], ti, poly))
            brushes.append({'contents': c, 'faces': [(n, p, t) for n, p, t, _ in out],
                            'polys': [q for _, _, _, q in out]})
    return brushes


def decompile_all(path):
    B = load(path)
    return {mi: decompile_model(B, mi) for mi in range(len(B['models']))}, B['ents'], B


def to_map_brush(br, default='NULL'):
    return [(n, p, t if t is not None else (default, None, None)) for n, p, t in br['faces']]


def main():
    brushes, ents, B = decompile_all(sys.argv[1])
    ws = dict(next(e for e in ents if e.get('classname') == 'worldspawn'))
    ws['mapversion'] = '220'
    if len(sys.argv) > 3:
        ws['wad'] = sys.argv[3]
    world = [to_map_brush(b) for b in brushes[0]]
    out_ents = []
    for e in ents:
        if e.get('classname') == 'worldspawn':
            continue
        e = dict(e)
        mdl = e.pop('model', '')
        if mdl.startswith('*'):
            e['__brushes'] = [to_map_brush(b) for b in brushes[int(mdl[1:])]]
        out_ents.append(e)
    write_map(sys.argv[2], ws, world, out_ents)
    nf = sum(len(b['faces']) for v in brushes.values() for b in v)
    nt = sum(1 for v in brushes.values() for b in v for f in b['faces'] if f[2] is not None)
    print("brushes", sum(len(v) for v in brushes.values()), "(world %d, sky %d)" % (len(brushes[0]), sum(1 for b in brushes[0] if b['contents'] == -6)),
          "faces", nf, "textured", nt, "entities", len(out_ents), "->", sys.argv[2])


if __name__ == '__main__':
    main()
