"""Build de_dust2_roofs.map: de_dust2 with the sky lifted off the rooftops, stairs up to the roofs and
HE grenades on them. usage: python build.py OUT.map [EMBEDDED.wad]

dust2's sky is a thin slab (mostly z 380..444) laid directly on the building tops, so the roofs are one
connected surface that nobody can stand on. Here every sky brush is removed and the column above it is
carved out of the solid up to ZC, where a new sky ceiling is laid. Faces the carve exposes get a
texture by rule: facing up -> roof, side faces backed by the map's outer solid -> sky (looks like the
old map edge), other side faces -> the wall texture of that brush.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
from bsp2map import decompile_all, split, extent, dot, MIN_THICK  # noqa: E402
from bspdecomp import write_map  # noqa: E402

HL = r'C:/Program Files (x86)/Steam/steamapps/common/Half-Life'
SRC = HL + '/cstrike/maps/de_dust2.bsp'
ZC = 600.0                  # new sky ceiling (old sky slab: 380..444, a few patches up to 640)
ROOF_TEX = 'SandCCrete'
WALL_TEX = '-0csSandWall'
MASK_DROP = 72.0            # see bspclipmerge mask below

brushes, ents, B = decompile_all(SRC)
P, N, LF = B['planes'], B['nodes'], B['leaves']


def contents(x, y, z):
    n = B['models'][0][9]
    while n >= 0:
        p = P[N[n][0]]
        n = N[n][1] if p[0] * x + p[1] * y + p[2] * z - p[3] >= 0 else N[n][2]
    return LF[-1 - n][0]


def outer_column(x, y):
    """the map's outer solid: no sky or air anywhere in this column of the original map"""
    return all(contents(x, y, z) == -2 for z in range(-316, 640, 8))


def as_faces(br):
    """decompiled brush -> polytope faces (outward n, d, polygon, texinfo)"""
    return [(n, dot(n, poly[0]), poly, t) for (n, p, t), poly in zip(br['faces'], br['polys'])]


def hull2d(pts):
    pts = sorted(set((round(p[0], 3), round(p[1], 3)) for p in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]          # counter-clockwise


def prism(poly2d, z0, z1):
    """carve volume as half-spaces (outward n, d)"""
    hs = [((0.0, 0.0, -1.0), -z0), ((0.0, 0.0, 1.0), z1)]
    for i in range(len(poly2d)):
        a, b = poly2d[i], poly2d[(i + 1) % len(poly2d)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(ex, ey)
        if ln < 1e-6:
            continue
        n = (ey / ln, -ex / ln, 0.0)
        hs.append((n, n[0] * a[0] + n[1] * a[1]))
    return hs


def subtract(faces, hs):
    """convex polytope minus convex half-space set -> list of convex pieces"""
    pts = [q for f in faces for q in f[2]]
    if any(min(dot(n, q) for q in pts) >= d - 0.01 for n, d in hs):
        return [faces]                 # disjoint
    out, rest = [], faces
    for n, d in hs:
        outside = split(rest, n, d, True, None)
        if len(outside) >= 4 and extent(outside) > MIN_THICK:
            out.append(outside)
        rest = split(rest, n, d, False, None)
        if len(rest) < 4:
            break
    return out


# ---- 1. carve the sky columns ----
world = brushes[0]
carves = []
for br in world:
    if br['contents'] == -6:
        pts = [q for poly in br['polys'] for q in poly]
        carves.append(prism(hull2d(pts), min(q[2] for q in pts), ZC + 16))
solids = [(as_faces(br), br) for br in world if br['contents'] == -2]
pieces = []
for faces, br in solids:
    cur = [faces]
    for hs in carves:
        nxt = []
        for f in cur:
            nxt.extend(subtract(f, hs))
        cur = nxt
    for f in cur:
        pieces.append((f, br))

# ---- 2. texture what the carve exposed ----
col_cache = {}


def wall_tex(br):
    side = [t for (n, p, t) in br['faces'] if t is not None and abs(n[2]) < 0.3 and t[0].lower() != 'sky']
    if not side:
        return (WALL_TEX, None, None)
    names = {}
    for t in side:
        names[t[0]] = names.get(t[0], 0) + 1
    return (max(names, key=names.get), None, None)      # name only: that face's axes would not fit this one


out_world = []
for faces, br in pieces:
    bf = []
    for n, d, poly, t in faces:
        if t is None:
            c = [sum(q[k] for q in poly) / len(poly) for k in range(3)]
            if n[2] > 0.7:
                t = (ROOF_TEX, None, None)
            elif n[2] < -0.7:
                t = ('sky', None, None)
            else:
                key = (round(c[0] - 8 * n[0]) // 16, round(c[1] - 8 * n[1]) // 16)
                if key not in col_cache:
                    col_cache[key] = outer_column(c[0] - 8 * n[0], c[1] - 8 * n[1])
                t = ('sky', None, None) if col_cache[key] else wall_tex(br)
        bf.append((n, poly[0], t))
    out_world.append(bf)

# ---- 3. new sky ceiling over the whole map ----
m0 = B['models'][0]
lo = (m0[0] - 16, m0[1] - 16, ZC)
hi = (m0[3] + 16, m0[4] + 16, ZC + 16)
sky = ('sky', None, None)
out_world.append([((0, 0, -1), lo, sky), ((0, 0, 1), hi, sky), ((-1, 0, 0), lo, sky), ((1, 0, 0), hi, sky),
                  ((0, -1, 0), lo, sky), ((0, 1, 0), hi, sky)])

# ---- 4. stairs and grenades (filled in below) ----
extra_world, extra_ents = [], []
try:
    from features import stairs, grenades   # noqa: E402
    extra_world = stairs()
    extra_ents = grenades()
except ImportError:
    pass

out_ents = []
for e in ents:
    if e.get('classname') == 'worldspawn':
        continue
    e = dict(e)
    mdl = e.pop('model', '')
    if mdl.startswith('*'):
        e['__brushes'] = [[(n, p, t if t is not None else ('NULL', None, None)) for n, p, t in br['faces']]
                          for br in brushes[int(mdl[1:])]]
    out_ents.append(e)

ws = dict(next(e for e in ents if e.get('classname') == 'worldspawn'))
ws['mapversion'] = '220'
wad = [HL + '/valve/halflife.wad', HL + '/cstrike/cs_dust.wad']
if len(sys.argv) > 2:
    wad.append(sys.argv[2])
ws['wad'] = ';'.join(wad)
# the carved columns, for bspclipmerge.py: the original player clipping is restored everywhere else
import json  # noqa: E402
# dust2 also has a CLIP layer ~24 units under the sky slab (keeps players off the wall tops); the mask
# reaches MASK_DROP below the old sky so that layer goes too
json.dump([[list(n) + [d + (MASK_DROP if n[2] < -0.5 else 0)] for n, d in hs] for hs in carves], open(os.path.splitext(sys.argv[1])[0] + '.mask.json', 'w'))
write_map(sys.argv[1], ws, out_world + extra_world, out_ents + extra_ents)
print('sky brushes removed', len(carves), 'solid pieces', len(pieces), 'stairs brushes', len(extra_world),
      'extra entities', len(extra_ents), '->', sys.argv[1])
