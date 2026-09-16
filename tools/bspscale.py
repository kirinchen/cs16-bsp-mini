"""Scale a GoldSrc (v30) BSP: geometry, collision hulls, entities.
Textures shrink with the geometry so the lightmap lump is reused unchanged.
usage: python bspscale.py in.bsp out.bsp SX SY SZ
"""
import struct, sys, math, re
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


def hull_plane(h, pidx):
    key = (h, pidx)
    if key not in plane_memo:
        nx, ny, nz, dist, t = planes[pidx]
        n0 = (nx, ny, nz)
        d0 = dist - expand(n0, HULLS[h])
        n2, d0s = xform_plane(n0, d0)
        plane_memo[key] = add_plane(n2, d0s + expand(n2, HULLS[h]))
    return plane_memo[key]


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
    new_clip[ni] = [hull_plane(h, pn), copy_clip(tree, h, c0), copy_clip(tree, h, c1)]
    return ni


for mi, m in enumerate(models):
    for h in (1, 2, 3):
        m[9 + h] = copy_clip((mi, h), h, m[9 + h])
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
