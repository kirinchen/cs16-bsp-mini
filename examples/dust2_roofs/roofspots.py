"""Pick grenade spots on the roofs of a built map: standing spots reachable from T spawn, feet at least
MINZ high, on visible floor (not a clip ledge), at least SPACING apart, not on the stairs.
usage: python roofspots.py MAP.bsp OUT.json [SPACING=128] [MINZ=290]"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools'))
from reachlib import Map, origin  # noqa: E402
from features import FLIGHTS, RISE, RUN, WIDTH  # noqa: E402

M = Map(sys.argv[1], grid=16, hulls=((1, 36),))
SP = float(sys.argv[3]) if len(sys.argv) > 3 else 128.0
MINZ = float(sys.argv[4]) if len(sys.argv) > 4 else 290.0
t = origin(next(e for e in M.ents if e.get('classname') == 'info_player_deathmatch'))
seen = M.bfs(M.near_spot(t))


def on_stairs(x, y):
    for _, fx, fy, f, r, up, out in FLIGHTS:
        L = ((r - f + RISE - 1) // RISE) * RUN
        xs = sorted((fx, fx + up[0] * L + out[0] * WIDTH))
        ys = sorted((fy, fy + up[1] * L + out[1] * WIDTH))
        if xs[0] - 48 <= x <= xs[1] + 48 and ys[0] - 48 <= y <= ys[1] + 48:
            return True
    return False


cand = []
for c in seen:
    x, y, z = c[0] * 16, c[1] * 16, c[2]
    if z < MINZ or on_stairs(x, y):
        continue
    if not all(M.contents(0, (x + dx, y + dy, z - 2)) != -1 for dx in (-12, 12) for dy in (-12, 12)):
        continue            # floor under the whole grenade footprint must be real geometry
    cand.append((x, y, z))
cand.sort(key=lambda p: (p[1], p[0]))
picked = []
bucket = {}
for p in cand:
    k = (int(p[0] // SP), int(p[1] // SP))
    near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in bucket.get((k[0] + dx, k[1] + dy), [])]
    if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= SP for q in near):
        picked.append(p)
        bucket.setdefault(k, []).append(p)
json.dump([(x, y, z + 16) for x, y, z in picked], open(sys.argv[2], 'w'))
print('roof spots', len(picked), 'from', len(cand), 'candidates ->', sys.argv[2])
