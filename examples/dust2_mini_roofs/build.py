"""de_dust2_mini (Zombie, 2010) + stairs up to its rooftops + HE grenades on the roofs, for a video shot.

The mini map's rooftops already connect (its author left hidden ways up); this only adds obvious
stairs and grenades. The map itself is NOT recompiled: the stairs are compiled on their own as
func_wall entities and grafted in (tools/bspgraft.py), so every original face, lightmap and
clip brush stays byte-identical.

usage:
  python build.py donor OUT_DIR          # writes OUT_DIR/stairs.map (compile it with sdHLT)
  python build.py finish DONOR.bsp OUT.bsp   # graft the compiled stairs, add the grenades
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', '..', 'tools')
sys.path.insert(0, TOOLS)
from bspdecomp import write_map  # noqa: E402
from reachlib import Map, origin  # noqa: E402

HL = r'C:/Program Files (x86)/Steam/steamapps/common/Half-Life'
SRC = HL + '/cstrike/maps/de_dust2_mini.bsp'
RISE, RUN, WIDTH = 16, 24, 64
TREAD = ('SandCCrete', None, None)
SIDE = ('SandTrim', None, None)

# found with sites.py (reachable street next to a wall whose top is a reachable roof, flat run along
# the wall, nothing overhead) and kept only where the foot has an open, flat approach with headroom
# (a low arch over the foot stopped the player in game): (name, top cell x, y, street z, roof z,
# toward wall, up[, tread run])
FLIGHTS = [
    ('t_spawn', 1216, -2448, -592, -480, (0, 1), (1, 0), 20),     # shorter treads: a pillar stands 8 units past a 24-run flight's foot
    ('t_west', 720, -2192, -592, -496, (1, 0), (0, 1)),
    ('short', 1872, -1680, -656, -512, (0, -1), (-1, 0)),
    ('long_a', 2224, -1536, -656, -480, (1, 0), (0, -1)),
    ('ct', 1776, -768, -608, -480, (0, 1), (-1, 0)),
    ('b', 768, -1136, -656, -528, (0, -1), (1, 0)),
]


def box(lo, hi):
    return [((0, 0, 1), hi, TREAD), ((0, 0, -1), lo, SIDE), ((1, 0, 0), hi, SIDE), ((-1, 0, 0), lo, SIDE),
            ((0, 1, 0), hi, SIDE), ((0, -1, 0), lo, SIDE)]


class Hull0:
    """point contents in the hull-0 node tree (reachlib.Map.contents only walks clipnode trees)"""
    def __init__(self, path):
        from bspdecomp import load
        B = load(path)
        self.P, self.N, self.L, self.head = B['planes'], B['nodes'], B['leaves'], B['models'][0][9]

    def __call__(self, x, y, z):
        n = self.head
        while n >= 0:
            p = self.P[self.N[n][0]]
            n = self.N[n][1] if p[0] * x + p[1] * y + p[2] * z - p[3] >= 0 else self.N[n][2]
        return self.L[-1 - n][0]


def surface(H, x, y, z_from, z_to):
    """top of the hull-0 solid below z_from (or z_to if none)"""
    z = z_from
    while H(x, y, z) == -1 and z > z_to:
        z -= 1
    return z + 1


def flight(H, x, y, floor, roof, d, up, run=RUN):
    """steps along the wall: the last tread is level with the roof behind it.
    floor / roof are reach.py feet heights at the top cell and on the roof. The wall line is where
    the ground under the top cell jumps up to the roof (an overhang counts: the stairs end under its edge)."""
    t = 0
    while surface(H, x + d[0] * t, y + d[1] * t, roof + 60, floor - 40) < roof - 20 and t < 96:
        t += 1
    face = (x + d[0] * t, y + d[1] * t)
    roof = surface(H, face[0] + d[0] * 8, face[1] + d[1] * 8, roof + 60, floor - 40)
    # tread heights above the floor: 8, 16, then +16 up to the roof. With 24-deep treads a 32-wide player
    # always stands on two of them, so stepping on from the SIDE of the flight lifts him to the second
    # tread: it has to be safely under the 18-unit step height (exactly 18 fails in game). The flight keeps the length a plain 16-rise
    # flight would have, so the treads get a little shallower.
    heights = [8.0, 16.0]
    while heights[-1] < roof - floor - 0.01:
        heights.append(min(roof - floor, heights[-1] + RISE))
    n = len(heights)
    length = int(math.ceil((roof - floor) / RISE)) * run
    tread = length / n
    end = (face[0] + up[0] * 4, face[1] + up[1] * 4)      # top tread ends half a cell past the top cell
    start = (end[0] - up[0] * length, end[1] - up[1] * length)
    brushes = []
    for k in range(n):
        a = (start[0] + up[0] * k * tread, start[1] + up[1] * k * tread)
        b = (a[0] + up[0] * tread - d[0] * WIDTH, a[1] + up[1] * tread - d[1] * WIDTH)
        lo = (round(min(a[0], b[0]), 2), round(min(a[1], b[1]), 2), floor - 8)
        hi = (round(max(a[0], b[0]), 2), round(max(a[1], b[1]), 2), round(floor + heights[k], 2))
        brushes.append(box(lo, hi))
    return brushes, face, floor, roof


def donor(out_dir):
    M = Map(SRC, grid=8, hulls=((1, 36),))
    H = Hull0(SRC)
    m0 = M.models[0]
    lo = [m0[0] - 128, m0[1] - 128, m0[2] - 128]
    hi = [m0[3] + 128, m0[4] + 128, m0[5] + 128]
    sky = ('sky', None, None)
    shell = []
    for ax in range(3):                         # hollow box, 16 thick
        for side in (0, 1):
            a, b = list(lo), list(hi)
            if side == 0:
                b[ax] = lo[ax] + 16
            else:
                a[ax] = hi[ax] - 16
            shell.append([((0, 0, 1), tuple(b), sky), ((0, 0, -1), tuple(a), sky), ((1, 0, 0), tuple(b), sky),
                          ((-1, 0, 0), tuple(a), sky), ((0, 1, 0), tuple(b), sky), ((0, -1, 0), tuple(a), sky)])
    ents = [{'classname': 'light_environment', 'origin': '%d %d %d' % (m0[0] + 64, m0[1] + 64, hi[2] - 64),
             '_ambient': '255 255 255 75', 'angles': '0 60 0', 'pitch': '-60', '_light': '250 245 78 250'},
            {'classname': 'info_player_start', 'origin': '%d %d %d' % ((m0[0] + m0[3]) / 2, (m0[1] + m0[4]) / 2, (m0[2] + m0[5]) / 2)}]
    for name, x, y, f, r, d, up, *run in FLIGHTS:
        b, face, floor, roof = flight(H, x, y, f, r, d, up, *run)
        ents.append({'classname': 'func_wall', 'targetname': 'stairs_' + name, '__brushes': b})
        print('%-8s wall face %s  %d steps  floor %d -> roof %d' % (name, face, len(b), floor, roof))
    ws = {'classname': 'worldspawn', 'mapversion': '220', 'skyname': 'sky_wasteland02',
          'wad': HL + '/valve/halflife.wad;' + HL + '/cstrike/cs_dust.wad'}
    os.makedirs(out_dir, exist_ok=True)
    write_map(os.path.join(out_dir, 'stairs.map'), ws, shell, ents)


def roof_spots(M, H, spacing=160):
    """standing spots reachable from T spawn that are at least 80 above the lowest street within 256,
    on visible floor (not a clip ledge)"""
    t = origin(next(e for e in M.ents if e.get('classname') == 'info_player_deathmatch'))
    seen = M.bfs(M.near_spot(t))
    low = {}
    for c in seen:
        k = (c[0] * M.G // 64, c[1] * M.G // 64)
        low[k] = min(low.get(k, 1e9), c[2])
    cand = []
    for c in seen:
        x, y, z = c[0] * M.G, c[1] * M.G, c[2]
        k = (x // 64, y // 64)
        street = min(low.get((k[0] + i, k[1] + j), 1e9) for i in range(-4, 5) for j in range(-4, 5))
        if z < street + 80:
            continue
        if not all(H(x + dx, y + dy, z - 2) != -1 for dx in (-10, 10) for dy in (-10, 10)):
            continue
        cand.append((x, y, z))
    cand.sort(key=lambda p: (p[1], p[0]))
    picked, bucket = [], {}
    for p in cand:
        k = (int(p[0] // spacing), int(p[1] // spacing))
        near = [q for i in (-1, 0, 1) for j in (-1, 0, 1) for q in bucket.get((k[0] + i, k[1] + j), [])]
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= spacing for q in near):
            picked.append(p)
            bucket.setdefault(k, []).append(p)
    return picked


def finish(donor_bsp, out):
    tmp = out + '.graft.bsp'
    subprocess.check_call([sys.executable, os.path.join(TOOLS, 'bspgraft.py'), SRC, donor_bsp, tmp])
    import bspents
    d, L, ents = bspents.read(tmp)
    M = Map(tmp, grid=8, hulls=((1, 36),))
    spots = roof_spots(M, Hull0(tmp))
    add = ''.join('{\n"classname" "armoury_entity"\n"item" "15"\n"count" "1"\n"origin" "%d %d %d"\n}\n' % (x, y, z + 16)
                  for x, y, z in spots)
    bspents.write(out, d, L, ents.rstrip('\0').rstrip() + '\n' + add)
    os.remove(tmp)
    json.dump(spots, open(os.path.join(HERE, 'roofspots.json'), 'w'))
    print('grenades', len(spots), '->', out)


if __name__ == '__main__':
    if sys.argv[1] == 'donor':
        donor(sys.argv[2])
    else:
        finish(sys.argv[2], sys.argv[3])
