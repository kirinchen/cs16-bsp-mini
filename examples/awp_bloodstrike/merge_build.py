"""Build awp_bloodstrike.map: cs_bloodstirke cut at y=0, halves pushed apart by 560 each way,
the gap filled with a 1696-wide arena carrying awp_map_mini's cover boxes, seam walls in the
middle of each joint. usage: python merge_build.py OUT.map"""
import sys, math, struct
sys.path.insert(0, r'C:\Users\DDT\Desktop\projects\cs16-bsp-mini\tools')
from bspdecomp import decompile, load, face_pts, box_brush, poly_brush, write_map

HL = r'C:/Program Files (x86)/Steam/steamapps/common/Half-Life'
BS = HL + '/cstrike/maps/cs_bloodstirke.bsp'
AWP = HL + '/cstrike/maps/awp_map_mini.bsp'
GAP = 560                # half of the arena length (arena y -560..560)
FLOOR_TOP, FLOOR_BOT = -336.0, -352.0
CEIL_BOT, CEIL_TOP = -128.0, -96.0
XW = 864.0               # outer extent of side walls; inner faces at +-832
SEAM_HALF, SEAM_T, SEAM_H = 424.0, 16.0, 128.0
STRETCH = 1696.0 / 800.0

boxes, ents, B = decompile(BS)

# ---- split blood strike at y = 0 and push the halves apart ----
def shifted(box, dy):
    b = dict(box)
    b['min'] = (box['min'][0], box['min'][1] + dy, box['min'][2])
    b['max'] = (box['max'][0], box['max'][1] + dy, box['max'][2])
    return b

bs_brushes = []
for bx in boxes:
    y0, y1 = bx['min'][1], bx['max'][1]
    if y1 <= 0:
        bs_brushes.append(box_brush(shifted(bx, -GAP)))
    elif y0 >= 0:
        bs_brushes.append(box_brush(shifted(bx, GAP)))
    else:  # crosses the cut: two pieces, cut faces hidden
        lo = dict(bx); lo['max'] = (bx['max'][0], 0.0, bx['max'][2]); lo['tex'] = dict(bx['tex']); lo['tex']['y+'] = None
        hi = dict(bx); hi['min'] = (bx['min'][0], 0.0, bx['min'][2]); hi['tex'] = dict(bx['tex']); hi['tex']['y-'] = None
        bs_brushes.append(box_brush(shifted(lo, -GAP)))
        bs_brushes.append(box_brush(shifted(hi, GAP)))

# textures to continue from blood strike: ceiling underside and the outer wall inner face
ceil_ti = next(b['tex']['z-'] for b in boxes if abs(b['min'][2] - CEIL_BOT) < 0.5 and b['tex'].get('z-'))
wall_ti = next(b['tex']['x+'] for b in boxes if abs(b["max"][0] + 832) < 0.5 and b['tex'].get('x+'))
floor_ti = next(b['tex']['z+'] for b in boxes if abs(b['max'][2] - FLOOR_TOP) < 0.5 and b['tex'].get('z+'))
print("continuing textures: ceiling", ceil_ti[0], "wall", wall_ti[0], "blood strike floor", floor_ti[0])

def aabb(mn, mx, tex):
    return box_brush({'min': mn, 'max': mx, 'tex': tex})

mid = []
# floor with the awp grass, ceiling and side walls continuing blood strike
mid.append(aabb((-XW, -GAP, FLOOR_BOT), (XW, GAP, FLOOR_TOP), {'z+': ('-0out_grss1', None, None)}))
mid.append(aabb((-XW, -GAP, CEIL_BOT), (XW, GAP, CEIL_TOP), {'z-': ceil_ti}))
mid.append(aabb((-XW, -GAP, FLOOR_TOP), (-832.0, GAP, CEIL_BOT), {'x+': wall_ti}))
mid.append(aabb((832.0, -GAP, FLOOR_TOP), (XW, GAP, CEIL_BOT), {'x-': (wall_ti[0], None, None)}))
# seam walls: centre 848 wide, 16 thick, 128 high, at both joints
SW = ('wet_wall06', None, None)
for yc in (GAP, -GAP):
    mid.append(aabb((-SEAM_HALF, yc - SEAM_T / 2, FLOOR_TOP), (SEAM_HALF, yc + SEAM_T / 2, FLOOR_TOP + SEAM_H),
                    {'x-': SW, 'x+': SW, 'y-': SW, 'y+': SW, 'z+': SW}))

# ---- awp cover boxes: top-face polygons of awp_map_mini, rotated 90deg, positions stretched ----
A = load(AWP)
m0 = A['models'][0]
floor_mini = min(min(p[2] for p in face_pts(A, f)) for f in A['faces'][m0[14]:m0[14] + m0[15]])
tops = []   # (ztop, texture, [(x,y)...]) per drawn top face
for f in A['faces'][m0[14]:m0[14] + m0[15]]:
    pl = A['planes'][f[0]]
    nz = pl[2] if f[1] == 0 else -pl[2]
    if nz < 0.99:
        continue
    pts = face_pts(A, f)
    ztop = pts[0][2]
    name = A['texnames'][A['texinfo'][f[4]][8]]
    if ztop - floor_mini < 4 or name == 'sky':
        continue
    poly = [(p[1] + 80.0, -p[0] + 80.0) for p in pts]               # rotate: x<-y+80, y<- -x+80
    tops.append((round(ztop, 1), name, poly))

# cluster split top faces back into whole boxes: same height, centroids within 120 units
def centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
clusters = []
for z, name, poly in tops:
    c = centroid(poly)
    for cl in clusters:
        if cl['z'] == z and math.dist(c, cl['c']) < 120:
            cl['pts'].extend(poly)
            cl['c'] = centroid(cl['pts'])
            break
    else:
        clusters.append({'z': z, 'name': name, 'pts': list(poly), 'c': c})

def hull(points):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in points))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 1e-6:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 1e-6:
            up.pop()
        up.append(p)
    h = lo[:-1] + up[:-1]
    # drop vertices that lie within 1 unit of the line through their neighbours (near-collinear)
    changed = True
    while changed and len(h) > 3:
        changed = False
        for i in range(len(h)):
            a, b, c = h[i - 1], h[i], h[(i + 1) % len(h)]
            ex, ey = c[0] - a[0], c[1] - a[1]
            ln = math.hypot(ex, ey) or 1.0
            dist = abs(ex * (b[1] - a[1]) - ey * (b[0] - a[0])) / ln
            if dist < 1.0:
                h.pop(i)
                changed = True
                break
    return h

nboxes = 0
for cl in clusters:
    poly = hull(cl['pts'])
    cx = sum(p[0] for p in poly) / len(poly)
    poly = [(p[0] + cx * (STRETCH - 1), p[1]) for p in poly]          # stretch positions, keep shape
    h = cl['z'] - floor_mini
    mid.append(poly_brush(poly, FLOOR_TOP, FLOOR_TOP + h, 'c2a4_lasgun', cl['name']))
    nboxes += 1
    print("  box h=%g at (%.0f, %.0f) %d sides" % (h, cx * STRETCH, cl['c'][1], len(poly)))
print("awp cover boxes:", nboxes)

# ---- entities ----
out_ents = []
for e in ents:
    c = e.get('classname')
    if c == 'worldspawn':
        continue
    e = dict(e)
    if 'origin' in e:
        x, y, z = (float(t) for t in e['origin'].split())
        y += -GAP if y < 0 else GAP
        e['origin'] = '%g %g %g' % (x, y, z)
    out_ents.append(e)
# arena lighting: 4 x 4 grid just under the ceiling, brighter than blood strike's 200
for x in (-636, -212, 212, 636):
    for y in (-420, -140, 140, 420):
        out_ents.append({'classname': 'light', 'origin': '%d %d -160' % (x, y), '_light': '210 210 200 260'})
worldspawn = {
    'classname': 'worldspawn', 'mapversion': '220', 'MaxRange': '4096',
    'message': 'Blood Strike x AWP mini',
    'wad': HL + '/valve/halflife.wad;' + HL + '/cstrike/cstrike.wad',
}
write_map(sys.argv[1], worldspawn, bs_brushes + mid, out_ents)
print("brushes", len(bs_brushes) + len(mid), "entities", len(out_ents), "->", sys.argv[1])
