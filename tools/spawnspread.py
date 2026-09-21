"""Spread a team's spawn points so no two are closer than MIN_DIST (CS treats a spawn with
another player within 64 units as occupied and telefrags once every spot is occupied).

usage: python spawnspread.py IN.bsp OUT.bsp CLASS WANT [MIN_DIST=72] [REACH=480]

CLASS is info_player_start (CT) or info_player_deathmatch (T). Existing spawns are kept
where they already satisfy the spacing; new ones are placed on walkable ground reachable
from the existing spawn zone within REACH units of path, closest to the zone first, with at
least 8 units of wall clearance. The lump is rewritten with the resulting WANT (or as many
as fit) spawns; other entities are untouched.
"""
import struct
import sys
import re
import math
from collections import deque

src, dst, cls, want = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
MIN_DIST = float(sys.argv[5]) if len(sys.argv) > 5 else 72.0
REACH = float(sys.argv[6]) if len(sys.argv) > 6 else 480.0
G = 16
MARGIN = 8

d = open(src, 'rb').read()
L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]


def arr(i, fmt):
    sz = struct.calcsize(fmt)
    o, l = L[i]
    return [struct.unpack_from(fmt, d, o + sz * k) for k in range(l // sz)]


planes = arr(1, '<3ffi')
clip = arr(9, '<ihh')
models = arr(14, '<3f3f3f4iiii')
o, l = L[0]
ents_txt = d[o:o + l].split(b'\0')[0].decode('latin1')
blocks = re.findall(r'\{[^}]*\}', ents_txt)


def kv(b):
    return dict(re.findall(r'"([^"]*)" "([^"]*)"', b))


def contents(hull, p):
    n = models[0][9 + hull]
    while n >= 0:
        pl = planes[clip[n][0]]
        n = clip[n][1] if pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2] - pl[3] >= 0 else clip[n][2]
    return n


def segs(hull, x, y, z0, z1):
    out = []
    stack = [(models[0][9 + hull], z0, z1)]
    while stack:
        n, a, b = stack.pop()
        if a >= b:
            continue
        if n < 0:
            if n in (-1, -3):
                out.append((a, b))
            continue
        pn, c1, c2 = clip[n]
        nx, ny, nz, dist, _ = planes[pn]
        base = nx * x + ny * y - dist
        if abs(nz) < 1e-9:
            stack.append((c1 if base >= 0 else c2, a, b))
            continue
        zs = -base / nz
        if zs <= a:
            stack.append((c1 if nz > 0 else c2, a, b))
        elif zs >= b:
            stack.append((c2 if nz > 0 else c1, a, b))
        else:
            stack.append(((c2 if nz > 0 else c1), a, zs))
            stack.append(((c1 if nz > 0 else c2), zs, b))
    out.sort()
    return out


ZMIN, ZMAX = models[0][2] - 64, models[0][5] + 64


def spots(cx, cy):
    """standing origins (z) at grid cell"""
    x, y = cx * G, cy * G
    return [a + 36 for a, b in segs(1, x, y, ZMIN, ZMAX) if b - a > 1]


def clearance(p):
    best = MARGIN
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(1, MARGIN + 1):
            q = (p[0] + dx * k, p[1] + dy * k, p[2])
            if contents(1, q) != -1 or contents(3, q) != -1:
                best = min(best, k - 1)
                break
    return best


spawn_blocks = [b for b in blocks if kv(b).get('classname') == cls]
existing = [tuple(float(t) for t in kv(b)['origin'].split()) for b in spawn_blocks]
if not existing:
    sys.exit("no %s in map" % cls)

# BFS over walkable cells from the existing spawns, tracking path length
dist = {}
q = deque()
for p in existing:
    c = (round(p[0] / G), round(p[1] / G), p[2])
    dist[c] = 0.0
    q.append(c)
while q:
    cx, cy, cz = q.popleft()
    dcur = dist[(cx, cy, cz)]
    if dcur > REACH:
        continue
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for z2 in spots(cx + dx, cy + dy):
            if z2 - cz <= 45 + 36 and cz - z2 <= 200:  # step/jump up, drop down
                key = (cx + dx, cy + dy, z2)
                nd = dcur + G
                if key not in dist or nd < dist[key]:
                    dist[key] = nd
                    q.append(key)

cands = []
for (cx, cy, z), dd in dist.items():
    p = (cx * G, cy * G, z)
    if contents(1, p) != -1 or contents(3, p) != -1:
        continue
    if not any(contents(1, (p[0], p[1], p[2] - k)) == -2 for k in (4, 8, 16, 24, 32, 40)):
        continue
    if clearance(p) < MARGIN:
        continue
    cands.append((dd, p))
cands.sort()

# greedy: originals first (in their order), then reachable candidates nearest the zone
chosen = []


def ok(p):
    return all(math.dist(p, c) >= MIN_DIST for c in chosen)


kept = 0
for p in existing:
    if ok(p) and len(chosen) < want:
        chosen.append(p)
        kept += 1
for dd, p in cands:
    if len(chosen) >= want:
        break
    if ok(p):
        chosen.append(p)
print("%s: %d existing (%d kept in place), %d candidates, result %d spawns, min spacing %.1f" % (
    cls, len(existing), kept, len(cands), len(chosen),
    min((math.dist(a, b) for i, a in enumerate(chosen) for b in chosen[i + 1:]), default=0)))
if len(chosen) < want:
    print("  WARNING: only %d fit within %g units of the spawn zone; raise REACH or lower MIN_DIST" % (len(chosen), REACH))

# rebuild entity lump: replace the class's blocks with the chosen set (angle from nearest original)
templates = [(tuple(float(t) for t in kv(b)['origin'].split()), kv(b)) for b in spawn_blocks]
new_blocks = []
for p in chosen:
    tk = min(templates, key=lambda t: math.dist(t[0], p))[1]
    e = dict(tk)
    e['origin'] = '%g %g %g' % p
    new_blocks.append('{\n' + '\n'.join('"%s" "%s"' % (k, v) for k, v in e.items()) + '\n}')
out_blocks = []
inserted = False
for b in blocks:
    if kv(b).get('classname') == cls:
        if not inserted:
            out_blocks.extend(new_blocks)
            inserted = True
        continue
    out_blocks.append(b)
new_ents = ('\n'.join(out_blocks) + '\n').encode('latin1') + b'\0'

lumps = {i: d[L[i][0]:L[i][0] + L[i][1]] for i in range(15)}
lumps[0] = new_ents
order = sorted(range(15), key=lambda i: L[i][0])
body = bytearray()
hdr = [None] * 15
pos = 4 + 8 * 15
for i in order:
    while (pos + len(body)) % 4:
        body.append(0)
    hdr[i] = (pos + len(body), len(lumps[i]))
    body += lumps[i]
open(dst, 'wb').write(struct.pack('<i', 30) + b''.join(struct.pack('<ii', *h) for h in hdr) + bytes(body))
print("wrote", dst)
