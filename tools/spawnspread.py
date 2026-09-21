"""Spread a team's spawn points so that WANT of them exist, each usable at the same time.

CS marks a spawn as occupied when FindEntityInSphere(spot, 64) finds a player, and that
engine call measures the distance from the spot to the player's bounding BOX (half size
16 x 16 x 36), not to the player's origin. Two spots therefore need a box distance above
64; once every spot is occupied the game telefrags whoever stands on the first one.
Default MIN_BOX is 80 for margin.

usage: python spawnspread.py IN.bsp OUT.bsp CLASS WANT [MIN_BOX=80] [REACH=640]

CLASS is info_player_start (CT) or info_player_deathmatch (T). Existing spawns are kept
where they already satisfy the spacing; new ones are placed on spots the walkability model
(reachlib) can reach from the existing spawn zone within REACH units of path, closest to the
zone first, standing hull only, with at least 8 units of wall clearance.
"""
import struct
import sys
import re
import math
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reachlib import Map, box_distance, origin

src, dst, cls, want = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
MIN_BOX = float(sys.argv[5]) if len(sys.argv) > 5 else 80.0
REACH = float(sys.argv[6]) if len(sys.argv) > 6 else 640.0
MARGIN = 8

M = Map(src, hulls=((1, 36),))          # standing only: a spawn must be a standing spot
existing_ents = [e for e in M.ents if e.get('classname') == cls]
existing = [origin(e) for e in existing_ents]
if not existing:
    sys.exit("no %s in map" % cls)


def clearance(p):
    return M.clearance(p, MARGIN)


starts = [M.near_spot(p) for p in existing]
dist = M.bfs([s for s in starts if s], max_dist=REACH)
cands = []
for (cx, cy, fz, h), dd in dist.items():
    if dd > REACH or h != 1:
        continue
    p = (cx * M.G, cy * M.G, fz + 36)
    if M.contents(1, p) != -1 or M.contents(3, p) != -1 or M.in_brush_model(1, p) or M.in_brush_model(3, p):
        continue
    if not any(M.contents(1, (p[0], p[1], p[2] - k)) == -2 for k in (4, 8, 16, 24, 32, 40)):
        continue
    if clearance(p) < MARGIN:
        continue
    cands.append((dd, p))
cands.sort()

chosen = []


def ok(p):
    return all(box_distance(p, c) >= MIN_BOX and box_distance(c, p) >= MIN_BOX for c in chosen)


kept = 0
for p in existing:
    if ok(p) and len(chosen) < want and clearance(p) >= 4:  # originals too close to a wall are replaced
        chosen.append(p)
        kept += 1
for dd, p in cands:
    if len(chosen) >= want:
        break
    if ok(p):
        chosen.append(p)
mind = min((min(box_distance(a, b), box_distance(b, a)) for i, a in enumerate(chosen) for b in chosen[i + 1:]), default=0)
print("%s: %d existing (%d kept in place), %d candidates, result %d spawns, min box distance %.1f" % (
    cls, len(existing), kept, len(cands), len(chosen), mind))
if len(chosen) < want:
    print("  WARNING: only %d fit within %g units of the spawn zone; raise REACH or lower MIN_BOX" % (len(chosen), REACH))

# rebuild the entity lump: replace this class's blocks with the chosen set (keys from nearest original)
d = open(src, 'rb').read()
L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]
o, l = L[0]
blocks = re.findall(r'\{[^}]*\}', d[o:o + l].split(b'\0')[0].decode('latin1'))


def kv(b):
    return dict(re.findall(r'"([^"]*)" "([^"]*)"', b))


templates = [(origin(e), e) for e in existing_ents]
new_blocks = []
for p in chosen:
    e = dict(min(templates, key=lambda t: math.dist(t[0], p))[1])
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
lumps = {i: d[L[i][0]:L[i][0] + L[i][1]] for i in range(15)}
lumps[0] = ('\n'.join(out_blocks) + '\n').encode('latin1') + b'\0'
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
