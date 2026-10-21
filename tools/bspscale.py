"""Scale a GoldSrc (v30) BSP: geometry, collision hulls, entities.
Textures shrink with the geometry so the lightmap lump is reused unchanged.
usage: python bspscale.py in.bsp out.bsp SX SY SZ
"""
import struct, sys, math, re, os
from collections import OrderedDict

src, dst = sys.argv[1], sys.argv[2]
SX, SY, SZ = (float(x) for x in sys.argv[3:6])
S = (SX, SY, SZ)
# optional: --drop classname[,classname...]  remove point entities of these classes
DROP = set()
for a in sys.argv[6:]:
    if a.startswith('--drop='):
        DROP |= set(a[7:].split(','))
d = open(src, 'rb').read()
ver, = struct.unpack_from('<i', d, 0)
assert ver == 30, "not a GoldSrc v30 BSP"
L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]


def lump(i):
    o, l = L[i]
    return d[o:o + l]


def arr(i, fmt):
    sz = struct.calcsize(fmt)
    o, l = L[i]
    return [list(struct.unpack_from(fmt, d, o + sz * k)) for k in range(l // sz)]


def pack(rows, fmt):
    return b''.join(struct.pack(fmt, *r) for r in rows)


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


HULLS = {1: (16, 16, 36), 2: (32, 32, 32), 3: (16, 16, 18)}

# ---------- planes ----------
PLANE = '<3ffi'
planes = arr(1, PLANE)


def xform_plane(n, dist):
    m = (n[0] / SX, n[1] / SY, n[2] / SZ)
    ln = math.sqrt(m[0] ** 2 + m[1] ** 2 + m[2] ** 2)
    n2 = (m[0] / ln, m[1] / ln, m[2] / ln)
    return n2, dist / ln


def plane_type(n):
    for i in range(3):
        if abs(abs(n[i]) - 1.0) < 1e-9:
            return i
    a = [abs(x) for x in n]
    return 3 + a.index(max(a))


def expand(n, h):
    return abs(n[0]) * h[0] + abs(n[1]) * h[1] + abs(n[2]) * h[2]


# only planes referenced by nodes/faces are kept (transformed); clipnode planes are rebuilt per hull
NODE = '<ihh3h3hHH'
nodes = arr(5, NODE)
FACE = '<HHiHH4Bi'
faces = arr(7, FACE)
new_planes = []
plane_index = {}


def add_plane(n2, d2):
    row = (f32(n2[0]), f32(n2[1]), f32(n2[2]), f32(d2), plane_type(n2))
    if row not in plane_index:
        plane_index[row] = len(new_planes)
        new_planes.append(list(row))
    return plane_index[row]


remap = {}
for idx in sorted({n[0] for n in nodes} | {f[0] for f in faces}):
    nx, ny, nz, dist, t = planes[idx]
    n2, d2 = xform_plane((nx, ny, nz), dist)
    remap[idx] = add_plane(n2, d2)
for n in nodes:
    n[0] = remap[n[0]]
for f in faces:
    f[0] = remap[f[0]]

# ---------- clipnodes: per-hull corrected planes ----------
CLIP = '<ihh'
clipnodes = arr(9, CLIP)
MODEL = '<3f3f3f4iiii'
models = arr(14, MODEL)
sys.setrecursionlimit(100000)
new_clip = []
copy_memo = {}        # (tree, old index) -> new index
plane_memo = {}


# ---------- which way was each clipnode's plane expanded? ----------
# The compiler expanded every brush face outward by expand(n, hull) along the FACE normal, but the
# plane lump stores canonical normals: the stored dist is d+e when the solid lies on the plane's back
# side and d-e when it lies on the front. Undoing the expansion therefore needs the solid side, per
# node (one plane index can be the expanded face of two different brushes in two regions). We find it
# by sampling the node's portal polygon (its plane clipped by every ancestor) just in front of / behind
# the plane and asking the two child subtrees what they contain.
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _contents_from(node, pt):
    n = node
    while n >= 0:
        pl = planes[clipnodes[n][0]]
        n = clipnodes[n][1] if _dot(pl, pt) - pl[3] >= 0 else clipnodes[n][2]
    return n


def _clip_poly(poly, n, dist, keep_front):
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        da, db = _dot(n, a) - dist, _dot(n, b) - dist
        if not keep_front:
            da, db = -da, -db
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            out.append(tuple(a[k] + t * (b[k] - a[k]) for k in range(3)))
    return out


def _area(poly):
    sx = sy = sz = 0.0
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        sx += a[1] * b[2] - a[2] * b[1]; sy += a[2] * b[0] - a[0] * b[2]; sz += a[0] * b[1] - a[1] * b[0]
    return 0.5 * math.sqrt(sx * sx + sy * sy + sz * sz)


def _fragments(node, poly):
    """push a polygon down a clipnode subtree: yields (leaf contents, fragment) for every leaf it crosses"""
    stack = [(node, poly)]
    while stack:
        n, p = stack.pop()
        if n < 0:
            yield n, p
            continue
        pl = planes[clipnodes[n][0]]
        nn = tuple(pl[:3])
        f = _clip_poly(p, nn, pl[3], True)
        if len(f) >= 3:
            stack.append((clipnodes[n][1], f))
        b = _clip_poly(p, nn, pl[3], False)
        if len(b) >= 3:
            stack.append((clipnodes[n][2], b))


node_votes = {}     # old clipnode index -> votes (debug: BSPSCALE_SIGNDUMP=file.json)
node_sign = {}      # old clipnode index -> +1 (solid behind: stored dist = d + e) / -1 (solid in front)
sign_stats = {'back': 0, 'front': 0, 'interior': 0, 'unresolved': 0}
_BIG = 65536.0
_EPS = 0.5


def _classify(node, ancestors, bbox):
    stack = [(node, ancestors)]
    while stack:
        node, ancestors = stack.pop()
        if node < 0 or node in node_sign:
            continue
        pi, c0, c1 = clipnodes[node]
        n = tuple(planes[pi][:3]); dist = planes[pi][3]
        o = tuple(n[k] * dist for k in range(3))
        a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = (n[1] * a[2] - n[2] * a[1], n[2] * a[0] - n[0] * a[2], n[0] * a[1] - n[1] * a[0])
        lu = math.sqrt(_dot(u, u)); u = (u[0] / lu, u[1] / lu, u[2] / lu)
        v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
        poly = [tuple(o[k] + s * _BIG * u[k] + t * _BIG * v[k] for k in range(3))
                for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        for (an, ad, front) in list(bbox) + ancestors:     # the model's box first: outside it is all solid
            poly = _clip_poly(poly, an, ad, front)
            if len(poly) < 3:
                break
        # exact portal fragments instead of point samples: a bevel plane of a slanted brush is a real face of
        # the expanded hull but only one hull width wide, which a sample grid over the whole portal can miss
        votes = {'front': 0.0, 'back': 0.0, 'solid': 0.0}
        if len(poly) >= 3:
            up = [tuple(q[k] + _EPS * n[k] for k in range(3)) for q in poly]
            for cf, frag in _fragments(c0, up):
                down = [tuple(q[k] - 2 * _EPS * n[k] for k in range(3)) for q in frag]
                for cb, sub in _fragments(c1, down):
                    f, b = cf != -1, cb != -1
                    if f != b:
                        votes['front' if f else 'back'] += _area(sub)
                    elif f:
                        votes['solid'] += _area(sub)
        node_votes[node] = votes
        if votes['front'] or votes['back']:
            node_sign[node] = 1 if votes['back'] >= votes['front'] else -1
            sign_stats['back' if node_sign[node] > 0 else 'front'] += 1
        else:
            node_sign[node] = 1          # inside solid, or no brush fragment on this portal: direction is moot
            sign_stats['solid' in votes and votes['solid'] and 'interior' or 'unresolved'] += 1
        stack.append((c1, ancestors + [(n, dist, False)]))
        stack.append((c0, ancestors + [(n, dist, True)]))


for m in models:
    for h in (1, 2, 3):
        pad = max(HULLS[h]) + 8.0
        box = []
        for k in range(3):
            n = [0.0, 0.0, 0.0]; n[k] = 1.0
            box.append((tuple(n), m[k] - pad, True))        # keep x >= mins - pad
            box.append((tuple(n), m[3 + k] + pad, False))   # keep x <= maxs + pad
        _classify(m[9 + h], [], box)
print("clip plane expansion side:", sign_stats)
if os.environ.get('BSPSCALE_SIGNDUMP'):
    import json
    json.dump({str(k): v for k, v in node_votes.items()}, open(os.environ['BSPSCALE_SIGNDUMP'], 'w'))


def hull_plane(h, pidx, sign):
    """undo the compiler's hull expansion (sign * expand), scale the bare plane, expand again"""
    key = (h, pidx, sign)
    if key not in plane_memo:
        nx, ny, nz, dist, t = planes[pidx]
        n0 = (nx, ny, nz)
        d0 = dist - sign * expand(n0, HULLS[h])
        n2, d0s = xform_plane(n0, d0)
        plane_memo[key] = add_plane(n2, d0s + sign * expand(n2, HULLS[h]))
    return plane_memo[key]


def hull_dist(h, pidx, sign):
    nx, ny, nz, dist, t = planes[pidx]
    n0 = (nx, ny, nz)
    n2, d0s = xform_plane(n0, dist - sign * expand(n0, HULLS[h]))
    return d0s + sign * expand(n2, HULLS[h])


node_old = {}
node_other = {}     # new clipnode index -> where its plane would sit with the opposite expansion sign


def copy_clip(tree, h, idx):
    """copy a clipnode tree for (model, hull) in PRE-ORDER: the engine requires every node of a
    hull to have an index >= that hull's head node (PM_HullPointContents: bad node number).
    Subtrees the compiler shared between hulls get a per-hull copy because the expansion differs."""
    if idx < 0:
        return idx
    key = (tree, idx)
    if key in copy_memo:
        return copy_memo[key]
    ni = len(new_clip)
    new_clip.append(None)
    copy_memo[key] = ni
    pn, c0, c1 = clipnodes[idx]
    new_clip[ni] = [hull_plane(h, pn, node_sign[idx]), copy_clip(tree, h, c0), copy_clip(tree, h, c1)]
    node_other[ni] = hull_dist(h, pn, -node_sign[idx])
    node_old[ni] = (idx, h)
    return ni


for mi, m in enumerate(models):
    for h in (1, 2, 3):
        m[9 + h] = copy_clip((mi, h), h, m[9 + h])
# ---------- sliver repair ----------
# Scaling shrinks the gaps between brushes but not the hull expansion, so a scaled expanded brush can
# poke through a split plane it stayed clear of in the original (bound: e * (1 - s) each side, plus
# the same again when the plane itself was expanded the other way). The subtree on the far side knows
# nothing about that brush, so a player there sinks into it. Along every node plane, the band between
# the two candidate positions (d_chosen, d_other) is where this can happen: solid fragments of the
# near child that reach into the band are re-inserted into the far child as convex brushes.
_TINY = 0.05


def _poly_cap(pts, n):
    """order coplanar points (normal n) into a convex polygon, dropping duplicates"""
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
    uniq.sort(key=lambda q: math.atan2(_dot(v, (q[0] - c[0], q[1] - c[1], q[2] - c[2])),
                                       _dot(u, (q[0] - c[0], q[1] - c[1], q[2] - c[2]))))
    return uniq


def _clip_polytope(faces, n, d, keep_front):
    """convex polytope (list of face polygons) clipped by a plane; returns (faces, cap polygon)"""
    out, on = [], []
    for f in faces:
        g = _clip_poly(f, n, d, keep_front)
        if len(g) >= 3 and _area(g) > 1e-6:
            out.append(g)
            on.extend(q for q in g if abs(_dot(n, q) - d) < 1e-4)
    cap = _poly_cap(on, n)
    if len(cap) >= 3 and _area(cap) > 1e-6:
        out.append(cap)
    return out, cap


def _box_polytope(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    return [[P[i] for i in f] for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4))]


def _extent(faces):
    pts = [q for f in faces for q in f]
    return min(max(q[k] for q in pts) - min(q[k] for q in pts) for k in range(3)) if pts else 0.0


def _vol(faces):
    """volume of a convex polytope: sum of pyramids from an interior point to each face"""
    pts = [q for f in faces for q in f]
    if len(faces) < 4 or not pts:
        return 0.0
    c = tuple(sum(q[k] for q in pts) / len(pts) for k in range(3))
    v = 0.0
    for f in faces:
        nx = ny = nz = 0.0
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)     # = 2 * area
        if ln < 1e-9:
            continue
        h = abs((nx * (f[0][0] - c[0]) + ny * (f[0][1] - c[1]) + nz * (f[0][2] - c[2])) / ln)
        v += ln * 0.5 * h / 3.0
    return v


_MINVOL = 0.5
_MINDEPTH = 2.0     # a brush poking less than this through a split plane is not worth clipnodes


def _newplane(i):
    r = new_planes[i]
    return (r[0], r[1], r[2]), r[3]


def _push_new(node, poly):
    """polygon down the NEW tree: yields (leaf, fragment, path of (plane index, side))"""
    stack = [(node, poly, [])]
    while stack:
        n, p, path = stack.pop()
        if n < 0:
            yield n, p, path
            continue
        pi = new_clip[n][0]
        nn, d = _newplane(pi)
        f = _clip_poly(p, nn, d, True)
        if len(f) >= 3:
            stack.append((new_clip[n][1], f, path + [(pi, True)]))
        b = _clip_poly(p, nn, d, False)
        if len(b) >= 3:
            stack.append((new_clip[n][2], b, path + [(pi, False)]))


repair_stats = {'nodes': 0, 'brushes': 0, 'clipnodes': 0}
pending = []        # (priority, -depth, node, child slot, polytope, contents) collected before any insertion


def _insert(node, Q, contents, skip=()):
    """insert convex solid Q (contents) into the new subtree at node; returns the (possibly new) root.
    skip: faces of Q that are boundaries of the leaf being descended into (they need no chain plane)"""
    if node >= 0:
        nn, d = _newplane(new_clip[node][0])
        f, cap = _clip_polytope(Q, nn, d, True)
        if _vol(f) > _MINVOL:
            new_clip[node][1] = _insert(new_clip[node][1], f, contents, skip + ((nn, d),))
        b, cap = _clip_polytope(Q, nn, d, False)
        if _vol(b) > _MINVOL:
            new_clip[node][2] = _insert(new_clip[node][2], b, contents, skip + ((nn, d),))
        return node
    if not (node == -1 or (contents == -2 and node != -2)):
        return node
    # brush chain: outside any face -> the old leaf, inside all faces -> contents
    c = [0.0, 0.0, 0.0]
    cnt = 0
    for f in Q:
        for q in f:
            c = [c[k] + q[k] for k in range(3)]
            cnt += 1
    c = [v / cnt for v in c]
    chain = []
    for f in Q:
        nx = ny = nz = 0.0           # Newell normal
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln < 1e-6:
            continue
        n = (nx / ln, ny / ln, nz / ln)
        if _dot(n, c) > _dot(n, f[0]):      # make it point away from the centroid
            n = (-n[0], -n[1], -n[2])
        d = _dot(n, f[0])
        same = lambda m, e: abs(_dot(m, n) - 1.0) < 1e-6 and abs(e - d) < 1e-3
        if any(same(m, e) or same((-m[0], -m[1], -m[2]), -e) for m, e in skip):
            continue        # the leaf already ends here
        if any(same(m, e) for m, e in chain):
            continue
        chain.append((n, d))
    if not chain:
        return contents if node == -1 else node
    head = contents
    for n, d in reversed(chain):
        ni = len(new_clip)
        # the engine evaluates axial planes as p[type] - dist, so an axial normal must be positive:
        # store the flipped plane and swap the children
        if max(n) < 0.5 and min(n) < -0.5:
            new_clip.append([add_plane((-n[0], -n[1], -n[2]), -d), head, node])   # front = inside
        else:
            new_clip.append([add_plane(n, d), node, head])     # front (outside) -> old leaf, back -> inside
        head = ni
    repair_stats['brushes'] += 1
    repair_stats['clipnodes'] += len(chain)
    return head


def _repair(root, region, h):
    stack = [(root, region)]
    while stack:
        ni, R = stack.pop()
        if ni < 0 or ni not in node_other:
            continue
        pi, c0, c1 = new_clip[ni]
        n, d = _newplane(pi)
        d_o = node_other[ni]
        front_R, cap = _clip_polytope(R, n, d, True)
        back_R, _ = _clip_polytope(R, n, d, False)
        if abs(d - d_o) > 1e-3 and len(cap) >= 3:
            if d_o < d:     # plane sits at the front bound: the front child's solids may reach down to d_o
                band, _ = _clip_polytope(back_R, n, d_o, True)
                src, dst_slot, eps = c0, 2, _EPS
            else:
                band, _ = _clip_polytope(front_R, n, d_o, False)
                src, dst_slot, eps = c1, 1, -_EPS
            DBG = os.environ.get('BSPSCALE_DEBUG') and node_old.get(ni) == (int(os.environ['BSPSCALE_DEBUG']), int(os.environ.get('BSPSCALE_DEBUG_HULL', 1)))
            if DBG:
                print('DBG node', ni, 'old', node_old[ni], 'n', n, 'd', d, 'd_o', d_o, 'cap', len(cap), 'band faces', len(band), 'extent', _extent(band))
            if _vol(band) > _MINVOL:
                probe = [tuple(q[k] + eps * n[k] for k in range(3)) for q in cap]
                for leaf, frag, path in _push_new(src, probe):
                    if leaf == -1:
                        continue
                    if DBG:
                        bb = [(min(q[k] for q in frag), max(q[k] for q in frag)) for k in range(3)]
                        print('  frag leaf', leaf, 'area', round(_area(frag), 1), 'bbox', [(round(a), round(b)) for a, b in bb])
                    Q = band
                    for ppi, side in path:
                        pn, pd = _newplane(ppi)
                        dp = _dot(pn, n)
                        # a duplicate of this node's own plane deeper in the child: in the original tree it
                        # bounded the fragment at the parent, so it must not cut the band
                        if (dp > 0.9999 and abs(pd - d) < 0.01) or (dp < -0.9999 and abs(pd + d) < 0.01):
                            continue
                        Q, _ = _clip_polytope(Q, pn, pd, side)
                        if len(Q) < 4:
                            break
                    if DBG:
                        print('    Q faces', len(Q), 'vol', round(_vol(Q), 3))
                    depth = max(_dot(n, q) for f in Q for q in f) - min(_dot(n, q) for f in Q for q in f) if Q else 0.0
                    if _vol(Q) > _MINVOL and depth >= _MINDEPTH:
                        pending.append((0 if h != 2 else 1, -depth, ni, dst_slot, Q, leaf))
        stack.append((new_clip[ni][2], back_R))
        stack.append((new_clip[ni][1], front_R))


for h in (1, 2, 3):
    for m in models:
        pad = max(HULLS[h]) + 8.0
        lo = [m[k] * S[k] - pad for k in range(3)]
        hi = [m[3 + k] * S[k] + pad for k in range(3)]
        _repair(m[9 + h], _box_polytope(lo, hi), h)
# hulls 1 (standing) and 3 (crouching) are what CS players walk with, so they go first, deepest crossing
# first; hull 2 (32x32x32, large monsters) last. Insertion stops at the engine's clipnode limit.
pending.sort(key=lambda t: t[:2])
_LIMIT = 32767
skipped = 0
touched = set()
for prio, ndepth, ni, dst_slot, Q, leaf in pending:
    if skipped:
        skipped += 1
        continue
    snap = [row[:] for row in new_clip] if len(new_clip) > _LIMIT - 400 else None
    new_clip[ni][dst_slot] = _insert(new_clip[ni][dst_slot], Q, leaf)
    touched.add(ni)
    if len(new_clip) > _LIMIT:
        new_clip[:] = snap
        skipped = 1
repair_stats['nodes'] = len(touched)
if skipped:
    print("WARNING: clipnode limit %d reached: %d of %d sliver brushes not inserted (shallowest, hull 2 first)" % (_LIMIT, skipped, len(pending)))
print("sliver repair: nodes", repair_stats['nodes'], "brushes", repair_stats['brushes'], "of", len(pending), "clipnodes added", repair_stats['clipnodes'])
assert len(new_clip) <= 32767, "too many clipnodes after per-hull split"
for m in models:
    for h in (1, 2, 3):
        root = m[9 + h]
        stack = [root]
        while stack:
            i = stack.pop()
            if i < 0:
                continue
            assert i >= root, "clipnode ordering broken"
            stack.extend(c for c in new_clip[i][1:3] if c > i)  # children always after parent
print("planes", len(planes), "->", len(new_planes), "clipnodes", len(clipnodes), "->", len(new_clip))
clipnodes = new_clip

# ---------- vertices ----------
verts = arr(3, '<3f')
new_verts = [[x * SX, y * SY, z * SZ] for x, y, z in verts]


# ---------- nodes / leaves / models bounds ----------
def sbox(mins, maxs):
    lo = [math.floor(v * s) for v, s in zip(mins, S)]
    hi = [math.ceil(v * s) for v, s in zip(maxs, S)]

    def clamp(v):
        return max(-32768, min(32767, v))
    return [clamp(v) for v in lo], [clamp(v) for v in hi]


for n in nodes:
    lo, hi = sbox(n[3:6], n[6:9])
    n[3:6] = lo
    n[6:9] = hi
LEAF = '<ii3h3hHH4B'
leaves = arr(10, LEAF)
for lf in leaves:
    lo, hi = sbox(lf[2:5], lf[5:8])
    lf[2:5] = lo
    lf[5:8] = hi
for m in models:
    m[0:3] = [v * s for v, s in zip(m[0:3], S)]
    m[3:6] = [v * s for v, s in zip(m[3:6], S)]
    m[6:9] = [v * s for v, s in zip(m[6:9], S)]

# ---------- texinfo per face (keep s/t identical -> lightmaps reusable) ----------
TEXINFO = '<8fii'
texinfo = arr(6, TEXINFO)
edges = arr(12, '<HH')
surfedges = [r[0] for r in arr(13, '<i')]


def face_verts(f):
    out = []
    for k in range(f[3]):
        se = surfedges[f[2] + k]
        e = edges[abs(se)]
        out.append(e[0] if se >= 0 else e[1])
    return out


new_texinfo = OrderedDict()


def ti_index(row):
    key = tuple(row)
    if key not in new_texinfo:
        new_texinfo[key] = len(new_texinfo)
    return new_texinfo[key]


LIGHT_LEN = L[8][1]


def evals(vec, pts):
    """coords under double and float32 evaluation"""
    dbl = [vec[0] * p[0] + vec[1] * p[1] + vec[2] * p[2] + vec[3] for p in pts]
    flt = [f32(f32(f32(f32(vec[0] * p[0]) + f32(vec[1] * p[1])) + f32(vec[2] * p[2])) + vec[3]) for p in pts]
    return dbl, flt


def ext(vals):
    return math.floor(min(vals) / 16), math.ceil(max(vals) / 16)


# infer the lightmap size hlrad actually wrote for each face (from lightofs spacing)
lit = sorted((f[9], i) for i, f in enumerate(faces) if f[9] >= 0)
lm_size = {}
for k, (off, i) in enumerate(lit):
    nxt = lit[k + 1][0] if k + 1 < len(lit) else LIGHT_LEN
    lm_size[i] = nxt - off


def nudge(vec, pts, bmin, bmax):
    """linear remap of the texture axis so the face's extent is (bmin,bmax) with a safe margin"""
    a = vec[:3]
    off = vec[3]
    dbl, flt = evals(vec, pts)
    lo, hi = min(dbl), max(dbl)
    m = 0.004 + 8 * 1.2e-7 * max(abs(lo), abs(hi), 1.0)
    if bmin == bmax:  # degenerate axis: whole face sits on one 16-boundary -> constant coordinate
        return [0.0, 0.0, 0.0, float(bmin * 16)]
    else:
        lo2 = min(max(lo, bmin * 16 + m), (bmin + 1) * 16 - m)
        hi2 = max(min(hi, bmax * 16 - m), (bmax - 1) * 16 + m)
    if hi > lo and hi2 > lo2:
        al = (hi2 - lo2) / (hi - lo)
    else:
        al = 1.0
    be = lo2 - al * lo
    na = [al * a[0] / SX, al * a[1] / SY, al * a[2] / SZ]
    return [f32(x) for x in na + [al * off + be]]


risky_faces = 0
mismatch = 0
fallback = 0
fb_amb = 0
for fi, f in enumerate(faces):
    ti = texinfo[f[4]]
    flags = ti[9]
    if flags & 1 or f[9] < 0:  # no lightmap: plain scale
        row = [ti[0] / SX, ti[1] / SY, ti[2] / SZ, ti[3], ti[4] / SX, ti[5] / SY, ti[6] / SZ, ti[7], ti[8], ti[9]]
        f[4] = ti_index([f32(x) for x in row[:8]] + row[8:])
        continue
    vi = face_verts(f)
    pts = [verts[i] for i in vi]
    nstyles = sum(1 for st in f[5:9] if st != 255)
    # candidate extents per axis under both evaluation modes
    cands = []
    for vec in (ti[0:4], ti[4:8]):
        dbl, flt = evals(vec, pts)
        opts = {ext(dbl), ext(flt)}
        lo, hi = min(dbl) / 16, max(dbl) / 16
        los = {math.floor(lo)} | ({round(lo) - 1, round(lo)} if abs(lo - round(lo)) < 2e-4 else set())
        his = {math.ceil(hi)} | ({round(hi), round(hi) + 1} if abs(hi - round(hi)) < 2e-4 else set())
        opts |= {(a, b) for a in los for b in his if b > a}
        cands.append(opts)
    want = lm_size[fi] // (3 * max(nstyles, 1))
    chosen = None
    dref = (ext(evals(ti[0:4], pts)[0]), ext(evals(ti[4:8], pts)[0]))
    for cs in cands[0]:
        for ct in cands[1]:
            if (cs[1] - cs[0] + 1) * (ct[1] - ct[0] + 1) == want:
                if chosen is None or (cs, ct) == dref:
                    chosen = (cs, ct)
    chosen_fallback = chosen is None
    if chosen is None:
        fallback += 1
        if len(cands[0]) > 1 or len(cands[1]) > 1:
            print('  FALLBACK face', fi, 'styles', nstyles, 'lmsize', lm_size[fi], 'want', want, 'cands', cands)
        dbl, _ = evals(ti[0:4], pts)
        dbl2, _ = evals(ti[4:8], pts)
        chosen = (ext(dbl), ext(dbl2))
    if len(cands[0]) > 1 or len(cands[1]) > 1:
        risky_faces += 1
        if chosen_fallback:
            fb_amb += 1
    sv = nudge(ti[0:4], pts, *chosen[0])
    tv = nudge(ti[4:8], pts, *chosen[1])
    row = sv + tv + [ti[8], ti[9]]
    npts = [[f32(v) for v in new_verts[i]] for i in vi]
    for vec, want_ext in ((row[0:4], chosen[0]), (row[4:8], chosen[1])):
        dbl, flt = evals(vec, npts)
        if ext(dbl) != want_ext or ext(flt) != want_ext:
            mismatch += 1
            print("  MISMATCH face", fi, "tex", ti[8], "want", want_ext, ext(dbl), ext(flt))
    f[4] = ti_index(row)
print("texinfo", len(texinfo), "->", len(new_texinfo), "faces", len(faces),
      "ambiguous", risky_faces, "size-fallback", fallback, "fallback+ambiguous", fb_amb, "extent mismatches", mismatch)
assert len(new_texinfo) <= 8192 and len(new_planes) <= 32767

# ---------- entities ----------
ents = lump(0).split(b'\0')[0].decode('latin1')
FEET = {'info_player_start', 'info_player_deathmatch'}
FLOOR = {'hostage_entity'}  # origin sits on the floor; game lifts the hull itself


def hull_contents(hull, p):
    n = models[0][9 + hull]
    while n >= 0:
        pl = new_planes[clipnodes[n][0]]
        n = clipnodes[n][1] if pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2] - pl[3] >= 0 else clipnodes[n][2]
    return n


MARGIN = 8


def clearance(q):
    """distance (capped at MARGIN) to the nearest solid in +-x / +-y, in both player hulls"""
    best = MARGIN
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(1, MARGIN + 1):
            r = (q[0] + dx * k, q[1] + dy * k, q[2])
            if hull_contents(1, r) != -1 or hull_contents(3, r) != -1:
                best = min(best, k - 1)
                break
    return best


def free_spot(p):
    """place a player-sized entity so it is in open space with some clearance to walls.
    A spawn exactly on a clip plane counts as inside the wall for the engine's float math."""
    def ok(q):
        if hull_contents(1, q) != -1 or hull_contents(3, q) != -1:
            return False
        # must have a floor right below (origin is 36 above the feet); no spawning in mid-air
        return any(hull_contents(1, (q[0], q[1], q[2] - k)) == -2 for k in (4, 8, 16, 24, 32, 40))
    if ok(p) and clearance(p) >= MARGIN:
        return p, False
    best = None  # (clearance, -distance, q)
    for dz in (0, 4, 8, 12, 16):
        for dx in range(-48, 49, 2):
            for dy in range(-48, 49, 2):
                q = (p[0] + dx, p[1] + dy, p[2] + dz)
                if not ok(q):
                    continue
                dd = dx * dx + dy * dy + dz * dz
                c = min(clearance(q), MARGIN)
                cand = (c, -dd, q)
                if best is None or cand > best:
                    best = cand
        if best and best[0] >= 4:
            break
    if best is None:
        print("  WARNING: no free spot near", p)
        return p, False
    if best[0] < 2:
        print("  WARNING: only %d units of clearance at" % best[0], best[2])
    return best[2], True


moved = []
dropped = []


def fix_block(m):
    body = m.group(1)
    pairs = re.findall(r'"([^"]*)" "([^"]*)"', body)
    kv = dict(pairs)
    cls = kv.get('classname', '')
    if cls in DROP:
        dropped.append(cls)
        return ''

    def sc(v, feet=False):
        try:
            x, y, z = (float(t) for t in v.split())
        except ValueError:
            return v
        z2 = (SZ * (z - 36) + 36) if feet else SZ * z
        q = (SX * x, SY * y, z2)
        if feet:
            q, did = free_spot(q)
            if did:
                moved.append((cls, v, q, 'clearance %d' % clearance(q)))
        elif cls in FLOOR:
            q2, did = free_spot((q[0], q[1], q[2] + 36))
            if did:
                q = (q2[0], q2[1], q2[2] - 36)
                moved.append((cls, v, q))
        return '%g %g %g' % q
    out = []
    for k, v in pairs:
        if k == 'origin':
            v = sc(v, cls in FEET)
        elif k == 'MaxRange':
            v = '%g' % (float(v) * max(S))
        elif (cls == 'func_tracktrain' and k in ('wheels', 'height', 'speed', 'startspeed'))                 or (cls == 'info_map_parameters' and k == 'bombradius')                 or (cls == 'env_explosion' and k == 'iMagnitude'):
            try:
                v = '%g' % (float(v) * SX)
            except ValueError:
                pass
        elif k == 'lip' and v not in ('0', ''):
            try:
                v = '%g' % (float(v) * min(S))
            except ValueError:
                pass
        elif k == 'message' and cls == 'worldspawn':
            v = v + ' (mini %g/%g/%g)' % S
        out.append('"%s" "%s"' % (k, v))
    return '{\n' + '\n'.join(out) + '\n}'


new_ents = re.sub(r'\{([^}]*)\}', fix_block, ents).encode('latin1') + b'\0'
print("entities dropped:", len(dropped), sorted(set(dropped)))
print("entities nudged out of walls:", len(moved))
for mv in moved:
    print("  ", mv)

# ---------- assemble ----------
out_lumps = {
    0: new_ents, 1: pack(new_planes, PLANE), 3: pack(new_verts, '<3f'), 5: pack(nodes, NODE),
    6: pack([list(k) for k in new_texinfo], TEXINFO), 7: pack(faces, FACE), 9: pack(clipnodes, CLIP),
    10: pack(leaves, LEAF), 14: pack(models, MODEL),
}
order = sorted(range(15), key=lambda i: L[i][0])
body = bytearray()
hdr = [None] * 15
pos = 4 + 8 * 15
for i in order:
    data = out_lumps.get(i, lump(i))
    while (pos + len(body)) % 4:
        body.append(0)
    hdr[i] = (pos + len(body), len(data))
    body += data
outb = struct.pack('<i', 30) + b''.join(struct.pack('<ii', *h) for h in hdr) + bytes(body)
open(dst, 'wb').write(outb)
print("wrote", dst, len(outb), "bytes")
