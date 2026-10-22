"""Stairs up to the roofs and HE grenades on them, for build.py.

A flight is a run of solid steps along a wall: RISE 16 (players step up to 18 without jumping), RUN 24,
WIDTH 96. Each step is one box from just under the street floor to its own tread, so the flight is
solid underneath. The last tread is level with the roof next to it.
"""
import json
import os

RISE, RUN, WIDTH = 16, 24, 96
TREAD = ('SandCCrete', None, None)
SIDE = ('SandTrim', None, None)

# (name, foot x, foot y, floor z, roof z, ascent direction, side away from the wall)
# foot = the corner of the first step on the wall side; the flight grows along `up` and away from the
# wall along `out`; found with sites.py on the lifted-sky map and checked in the top-down height map
FLIGHTS = [
    ('t_spawn', -1424, -1024, 128, 336, (1, 0), (0, 1)),
    ('mid', -128, 560, 0, 336, (0, 1), (-1, 0)),
    ('long_a', 1616, 1040, 0, 352, (0, 1), (-1, 0)),
    ('ct', 128, 2304, 128, 384, (0, 1), (-1, 0)),
    ('b_north', -1280, 3232, 128, 384, (0, 1), (-1, 0)),
    # roof to the two taller (512) blocks next to T spawn
    ('t_south_high', -1936, -1152, 352, 512, (1, 0), (0, -1)),
    ('t_north_high', -1024, -240, 352, 512, (0, 1), (1, 0)),
]


def box(lo, hi, top=TREAD, side=SIDE):
    return [((0, 0, 1), hi, top), ((0, 0, -1), lo, side), ((1, 0, 0), hi, side), ((-1, 0, 0), lo, side),
            ((0, 1, 0), hi, side), ((0, -1, 0), lo, side)]


def flight(x, y, floor, roof, up, out):
    steps = (roof - floor + RISE - 1) // RISE
    brushes = []
    for k in range(steps):
        z = min(roof, floor + (k + 1) * RISE)
        a = (x + up[0] * k * RUN, y + up[1] * k * RUN)
        b = (a[0] + up[0] * RUN + out[0] * WIDTH, a[1] + up[1] * RUN + out[1] * WIDTH)
        lo = (min(a[0], b[0]), min(a[1], b[1]), floor - 8)
        hi = (max(a[0], b[0]), max(a[1], b[1]), z)
        brushes.append(box(lo, hi))
    top_end = (x + up[0] * steps * RUN, y + up[1] * steps * RUN)
    return brushes, top_end


def stairs():
    out = []
    for name, x, y, f, r, up, side in FLIGHTS:
        b, end = flight(x, y, f, r, up, side)
        out.extend(b)
    return out


def grenades():
    """armoury_entity item 15 = HE grenade; spots come from roofspots.json (written by roofspots.py)"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'roofspots.json')
    if not os.path.exists(p):
        return []
    return [{'classname': 'armoury_entity', 'item': '15', 'count': '1', 'origin': '%d %d %d' % tuple(s)}
            for s in json.load(open(p))]
