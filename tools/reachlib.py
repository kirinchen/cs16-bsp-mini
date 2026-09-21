"""Walkability model shared by reach.py and spawnspread.py.

A player-sized box is moved over an XY grid using the map's own collision hulls (standing
hull 1, crouching hull 3). Solid brush entities (func_wall, func_breakable, doors...) count
as solid; doors and ladders are not climbed. Movement: step/jump up to JUMP units, drop any
distance. Each grid cell is sampled at nine sub-offsets so narrow gaps are not missed.
"""
import struct
import re
import math
from collections import deque

SOLID_CLS = {'func_wall', 'func_breakable', 'func_button', 'func_train', 'func_tracktrain', 'func_pushable'}
PASS = {-1, -3, -16}   # empty, water, ladder


class Map:
    def __init__(self, path, grid=8, hulls=((1, 36), (3, 18))):
        d = open(path, 'rb').read()
        L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]

        def arr(i, fmt):
            sz = struct.calcsize(fmt)
            o, l = L[i]
            return [struct.unpack_from(fmt, d, o + sz * k) for k in range(l // sz)]
        self.planes = arr(1, '<3ffi')
        self.clip = arr(9, '<ihh')
        self.models = arr(14, '<3f3f3f4iiii')
        o, l = L[0]
        self.ents = [dict(re.findall(r'"([^"]*)" "([^"]*)"', b)) for b in re.findall(r'\{([^}]*)\}', d[o:o + l].decode('latin1'))]
        self.solid_models = [int(e['model'][1:]) for e in self.ents
                             if e.get('classname') in SOLID_CLS and e.get('model', '').startswith('*')]
        self.G = grid
        self.HULLS = hulls
        g = grid / 2
        self.OFFS = [(0, 0), (g, 0), (-g, 0), (0, g), (0, -g), (g, g), (-g, -g), (g, -g), (-g, g)]
        self.ZMIN, self.ZMAX = self.models[0][2] - 64, self.models[0][5] + 64
        self._cache = {}

    def contents(self, hull, p, model=0):
        n = self.models[model][9 + hull]
        while n >= 0:
            pl = self.planes[self.clip[n][0]]
            n = self.clip[n][1] if pl[0] * p[0] + pl[1] * p[1] + pl[2] * p[2] - pl[3] >= 0 else self.clip[n][2]
        return n

    def in_brush_model(self, hull, p):
        for m in self.solid_models:
            mm = self.models[m]
            if mm[0] - 40 <= p[0] <= mm[3] + 40 and mm[1] - 40 <= p[1] <= mm[4] + 40 and mm[2] - 80 <= p[2] <= mm[5] + 80:
                if self.contents(hull, p, m) == -2:
                    return True
        return False

    def segs(self, hull, model, x, y, z0, z1):
        """passable z-intervals along a vertical line"""
        out = []
        stack = [(self.models[model][9 + hull], z0, z1)]
        while stack:
            n, a, b = stack.pop()
            if a >= b:
                continue
            if n < 0:
                if n in PASS:
                    out.append((a, b))
                continue
            pn, c1, c2 = self.clip[n]
            nx, ny, nz, dist, _ = self.planes[pn]
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
        merged = []
        for a, b in out:
            if merged and a <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def blocked(self, hull, x, y, a, b):
        """subtract the solid brush models from an interval"""
        ivs = [(a, b)]
        for m in self.solid_models:
            mm = self.models[m]
            if not (mm[0] - 40 <= x <= mm[3] + 40 and mm[1] - 40 <= y <= mm[4] + 40):
                continue
            free = self.segs(hull, m, x, y, a, b)
            new = []
            for ia, ib in ivs:
                for fa, fb in free:
                    lo, hi = max(ia, fa), min(ib, fb)
                    if hi > lo:
                        new.append((lo, hi))
            ivs = new
        return ivs

    def spots(self, cx, cy):
        """standable (feet_z, hull) spots at a grid cell"""
        key = (cx, cy)
        if key in self._cache:
            return self._cache[key]
        res = []
        seen_z = set()
        for ox, oy in self.OFFS:
            x, y = cx * self.G + ox, cy * self.G + oy
            for hull, half in self.HULLS:
                for a, b in self.segs(hull, 0, x, y, self.ZMIN, self.ZMAX):
                    for ia, ib in self.blocked(hull, x, y, a, b):
                        k = (round((ia - half) / 4), hull)
                        if ib - ia > 1 and k not in seen_z:
                            seen_z.add(k)
                            res.append((ia - half, hull))
        self._cache[key] = res
        return res

    def near_spot(self, p):
        """(cx, cy, feet_z, hull) nearest to a world point (origin 36 above feet)"""
        cx, cy = round(p[0] / self.G), round(p[1] / self.G)
        best = None
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                for fz, h in self.spots(cx + dx, cy + dy):
                    dd = abs(fz - (p[2] - 36)) + (dx * dx + dy * dy) * self.G
                    if best is None or dd < best[0]:
                        best = (dd, (cx + dx, cy + dy, fz, h))
        return best[1] if best else None

    def bfs(self, starts, jump=45, max_dist=None):
        """reachable spots from one or more start spots; returns {spot: path length}"""
        if starts and not isinstance(starts[0], tuple):
            starts = [starts]
        dist = {s: 0.0 for s in starts if s}
        q = deque(dist)
        while q:
            cur = q.popleft()
            cx, cy, fz, h = cur
            dcur = dist[cur]
            if max_dist is not None and dcur > max_dist:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0)):
                for fz2, h2 in self.spots(cx + dx, cy + dy):
                    if fz2 - fz > jump:
                        continue
                    if dx == 0 and dy == 0 and (h2 == h or abs(fz2 - fz) > jump):
                        continue
                    n = (cx + dx, cy + dy, fz2, h2)
                    nd = dcur + (self.G if (dx or dy) else 0)
                    if n not in dist or nd < dist[n]:
                        dist[n] = nd
                        q.append(n)
        return dist

    def connected(self, seen, p):
        sp = self.near_spot(p)
        if sp is None:
            return False
        return sp in seen or any(c[0] == sp[0] and c[1] == sp[1] and abs(c[2] - sp[2]) < 40 for c in seen)


def box_distance(a, b, half=(16, 16, 36)):
    """distance from point a to a player box centred on b: what FindEntityInSphere measures"""
    return math.sqrt(sum(max(0.0, abs(a[i] - b[i]) - half[i]) ** 2 for i in range(3)))


def origin(e):
    return tuple(float(t) for t in e['origin'].split())
