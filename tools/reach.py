"""Reachability check: BFS a player-sized box over a grid using the BSP collision hulls.
usage: python reach.py map.bsp [grid=8] [stand] [dump=cells.json]
  grid  : XY sample spacing in units (8 is a good default; smaller is slower)
  stand : only use the standing hull; default allows crouching too
  dump= : write the reachable cell set to a JSON file (for reachdiff.py)
Reports whether CT spawn, T spawn and the objectives are reachable from the first T spawn,
and whether every spawn of both teams is connected.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reachlib import Map, origin

path = sys.argv[1]
G = int(sys.argv[2]) if len(sys.argv) > 2 else 8
hulls = ((1, 36),) if 'stand' in sys.argv[3:] else ((1, 36), (3, 18))
M = Map(path, grid=G, hulls=hulls)

T = [origin(e) for e in M.ents if e.get('classname') == 'info_player_deathmatch']
CT = [origin(e) for e in M.ents if e.get('classname') == 'info_player_start']
goals = {'CT spawn': CT[0], 'T spawn': T[0]}
for e in M.ents:
    if e.get('classname') in ('func_bomb_target', 'hostage_entity', 'func_hostage_rescue'):
        if e.get('model', '').startswith('*'):
            m = M.models[int(e['model'][1:])]
            goals[e['classname'] + e['model']] = ((m[0] + m[3]) / 2, (m[1] + m[4]) / 2, m[2] + 36)
        else:
            goals[e['classname'] + e.get('origin', '')] = origin(e)

start = M.near_spot(T[0])
print("start", start)
seen = M.bfs(start)
cells = {(c[0], c[1]) for c in seen}
print("reachable spots", len(seen), "cells", len(cells))
for name, p in goals.items():
    print("  %-32s %s  %s" % (name, 'REACHABLE' if M.connected(seen, p) else 'NOT reachable', M.near_spot(p)))
print("both-spawn reachable:", all(M.connected(seen, p) for p in T + CT))
for a in sys.argv[3:]:
    if a.startswith('dump='):
        import json
        json.dump(sorted(set((c[0], c[1], round(c[2])) for c in seen)), open(a[5:], 'w'))
