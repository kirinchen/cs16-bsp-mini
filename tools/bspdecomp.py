"""Minimal GoldSrc BSP -> .map decompiler for axis-aligned maps, plus a Valve-220 .map writer.

Solid space in a GoldSrc BSP is the set of regions of the hull-0 node tree that end in the
shared solid leaf. For maps built only from axis-aligned brushes every such region is a box,
so each becomes one brush. Faces of a box that coincide with a drawn BSP face get that face's
texture and texture axes; faces nobody could see get NULL (removed at compile time).

usage: python bspdecomp.py MAP.bsp OUT.map [wadlist]
   or import: boxes, ents, meta = decompile('map.bsp'); write_map('out.map', worldspawn, brushes, ents)
"""
import struct
import sys
import re
import math


def load(path):
    d = open(path, 'rb').read()
    L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]

    def arr(i, fmt):
        sz = struct.calcsize(fmt)
        o, l = L[i]
        return [struct.unpack_from(fmt, d, o + sz * k) for k in range(l // sz)]
    B = {
        'planes': arr(1, '<3ffi'), 'nodes': arr(5, '<ihh3h3hHH'), 'leaves': arr(10, '<ii3h3hHH4B'),
        'faces': arr(7, '<HHiHH4Bi'), 'texinfo': arr(6, '<8fii'), 'verts': arr(3, '<3f'),
        'edges': arr(12, '<HH'), 'surfedges': [r[0] for r in arr(13, '<i')], 'models': arr(14, '<3f3f3f4iiii'),
    }
    o, l = L[2]
    nt, = struct.unpack_from('<i', d, o)
    offs = struct.unpack_from('<%di' % nt, d, o + 4)
    B['texnames'] = [d[o + t:o + t + 16].split(b'\0')[0].decode('latin1') for t in offs]
    o, l = L[0]
    B['ents'] = [dict(re.findall(r'"([^"]*)" "([^"]*)"', b)) for b in re.findall(r'\{([^}]*)\}', d[o:o + l].decode('latin1'))]
    return B


def face_pts(B, f):
    pts = []
    for k in range(f[3]):
        se = B['surfedges'][f[2] + k]
        e = B['edges'][abs(se)]
        pts.append(B['verts'][e[0] if se >= 0 else e[1]])
    return pts


def decompile(path, margin=16):
    """return (boxes, ents) ; box = dict(min=(x,y,z), max=(x,y,z), tex={side: texinfo-or-None})
    side in 'x-','x+','y-','y+','z-','z+' ; texinfo = (name, (sx,sy,sz,soff), (tx,ty,tz,toff))"""
    B = load(path)
    m0 = B['models'][0]
    world = [m0[0] - margin, m0[1] - margin, m0[2] - margin, m0[3] + margin, m0[4] + margin, m0[5] + margin]
    planes = B['planes']
    boxes = []

    def walk(n, box):
        if n < 0:
            leaf = -1 - n
            if leaf == 0:  # shared solid leaf
                boxes.append(list(box))
            return
        pl = planes[B['nodes'][n][0]]
        axis = pl[4]
        assert axis <= 2, "non-axial plane in node tree; this decompiler only handles axis-aligned maps"
        dist = pl[3]
        if pl[axis] < 0:  # normal pointing negative: front side is coordinate <= -dist
            dist = -dist
            front, back = B['nodes'][n][2], B['nodes'][n][1]
        else:
            front, back = B['nodes'][n][1], B['nodes'][n][2]
        b = list(box)
        b[axis] = max(b[axis], dist)          # front: coord >= dist
        if b[axis] < b[axis + 3]:
            walk(front, b)
        b = list(box)
        b[axis + 3] = min(b[axis + 3], dist)  # back: coord <= dist
        if b[axis] < b[axis + 3]:
            walk(back, b)

    sys.setrecursionlimit(10000)
    walk(m0[9], world)

    # drawn faces indexed by (axis, facing, coordinate)
    drawn = {}
    for f in B['faces'][m0[14]:m0[14] + m0[15]]:
        pl = planes[f[0]]
        if pl[4] > 2:
            continue
        axis = pl[4]
        sign = 1 if pl[axis] > 0 else -1
        if f[1] == 1:
            sign = -sign
        pts = face_pts(B, f)
        coord = round(pts[0][axis], 2)
        ti = B['texinfo'][f[4]]
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        drawn.setdefault((axis, sign, coord), []).append((lo, hi, (B['texnames'][ti[8]], ti[0:4], ti[4:8])))

    sides = {'x-': (0, -1), 'x+': (0, 1), 'y-': (1, -1), 'y+': (1, 1), 'z-': (2, -1), 'z+': (2, 1)}
    out = []
    for b in boxes:
        tex = {}
        for name, (axis, sign) in sides.items():
            coord = round(b[axis] if sign < 0 else b[axis + 3], 2)
            best = None
            for lo, hi, ti in drawn.get((axis, sign, coord), []):
                ov = 1.0
                for i in range(3):
                    if i == axis:
                        continue
                    ov *= max(0.0, min(hi[i], b[i + 3]) - max(lo[i], b[i]))
                if ov > 0 and (best is None or ov > best[0]):
                    best = (ov, ti)
            tex[name] = best[1] if best else None
        out.append({'min': tuple(b[:3]), 'max': tuple(b[3:]), 'tex': tex})
    return out, B['ents'], B


def box_brush(box, default='NULL'):
    """turn a decompiled box into a brush: list of (normal, point, texinfo)"""
    mn, mx = box['min'], box['max']
    faces = []
    for name, (axis, sign) in {'x-': (0, -1), 'x+': (0, 1), 'y-': (1, -1), 'y+': (1, 1), 'z-': (2, -1), 'z+': (2, 1)}.items():
        n = [0, 0, 0]
        n[axis] = sign
        p = list(mn if sign < 0 else mx)
        ti = box['tex'].get(name)
        if ti is None:
            ti = (default, None, None)
        faces.append((tuple(n), tuple(p), ti))
    return faces


def poly_brush(poly, zbot, ztop, side_tex, top_tex, bottom_tex='NULL'):
    """vertical prism from a convex polygon (list of (x,y), any winding) between zbot and ztop"""
    # ensure counter-clockwise (positive area)
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    if area < 0:
        poly = poly[::-1]
    faces = [((0, 0, 1), (poly[0][0], poly[0][1], ztop), (top_tex, None, None)),
             ((0, 0, -1), (poly[0][0], poly[0][1], zbot), (bottom_tex, None, None))]
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(ex, ey)
        n = (ey / ln, -ex / ln, 0.0)  # outward for CCW polygon
        faces.append((n, (a[0], a[1], zbot), (side_tex, None, None)))
    return faces


def tex_axes(n, ti):
    """Valve 220 texture axes for a face: returns (uvec, uoff, vvec, voff, sx, sy)"""
    name, svec, tvec = ti
    if svec is not None:
        ls = math.sqrt(svec[0] ** 2 + svec[1] ** 2 + svec[2] ** 2)
        lt = math.sqrt(tvec[0] ** 2 + tvec[1] ** 2 + tvec[2] ** 2)
        return ((svec[0] / ls, svec[1] / ls, svec[2] / ls), svec[3], (tvec[0] / lt, tvec[1] / lt, tvec[2] / lt), tvec[3], 1 / ls, 1 / lt)
    # default world-aligned axes for generated faces
    ax = max(range(3), key=lambda i: abs(n[i]))
    if ax == 2:
        return ((1, 0, 0), 0, (0, -1, 0), 0, 1, 1)
    if ax == 0:
        return ((0, 1, 0), 0, (0, 0, -1), 0, 1, 1)
    return ((1, 0, 0), 0, (0, 0, -1), 0, 1, 1)


def plane_points(n, p):
    """three points whose hlcsg normal (p0-p1)x(p2-p1) equals n"""
    n = tuple(float(v) for v in n)
    up = (0, 0, 1) if abs(n[2]) < 0.9 else (1, 0, 0)
    # a = up x n ; b = n x a  ->  a x b = n
    a = (up[1] * n[2] - up[2] * n[1], up[2] * n[0] - up[0] * n[2], up[0] * n[1] - up[1] * n[0])
    b = (n[1] * a[2] - n[2] * a[1], n[2] * a[0] - n[0] * a[2], n[0] * a[1] - n[1] * a[0])
    p1 = p
    p0 = (p[0] + a[0] * 64, p[1] + a[1] * 64, p[2] + a[2] * 64)
    p2 = (p[0] + b[0] * 64, p[1] + b[1] * 64, p[2] + b[2] * 64)
    return p0, p1, p2


def fmt(v):
    return ('%.6f' % v).rstrip('0').rstrip('.') if abs(v - round(v)) > 1e-9 else '%d' % round(v)


def write_map(path, worldspawn, brushes, ents):
    out = ['{']
    for k, v in worldspawn.items():
        out.append('"%s" "%s"' % (k, v))
    for br in brushes:
        out.append('{')
        for n, p, ti in br:
            p0, p1, p2 = plane_points(n, p)
            u, uo, v, vo, sx, sy = tex_axes(n, ti)
            out.append('( %s %s %s ) ( %s %s %s ) ( %s %s %s ) %s [ %s %s %s %s ] [ %s %s %s %s ] 0 %s %s' % (
                fmt(p0[0]), fmt(p0[1]), fmt(p0[2]), fmt(p1[0]), fmt(p1[1]), fmt(p1[2]), fmt(p2[0]), fmt(p2[1]), fmt(p2[2]),
                ti[0], fmt(u[0]), fmt(u[1]), fmt(u[2]), fmt(uo), fmt(v[0]), fmt(v[1]), fmt(v[2]), fmt(vo), fmt(sx), fmt(sy)))
        out.append('}')
    out.append('}')
    for e in ents:
        if e.get('classname') == 'worldspawn':
            continue
        out.append('{')
        for k, v in e.items():
            out.append('"%s" "%s"' % (k, v))
        out.append('}')
    open(path, 'w', newline='\n').write('\n'.join(out) + '\n')


if __name__ == '__main__':
    boxes, ents, B = decompile(sys.argv[1])
    ws = next(e for e in ents if e.get('classname') == 'worldspawn')
    ws = dict(ws)
    ws['mapversion'] = '220'
    if len(sys.argv) > 3:
        ws['wad'] = sys.argv[3]
    brushes = [box_brush(b) for b in boxes]
    write_map(sys.argv[2], ws, brushes, ents)
    nulls = sum(1 for b in boxes for t in b['tex'].values() if t is None)
    print("boxes", len(boxes), "faces textured", 6 * len(boxes) - nulls, "NULL", nulls, "entities", len(ents) - 1, "->", sys.argv[2])
