---
name: bsp-mini
description: Make a scaled-down ("mini") version of a compiled GoldSrc / Counter-Strike 1.6 map (.bsp) without decompiling. Use when the user asks to shrink, scale, miniaturise or make a mini version of a .bsp map, or asks whether a map can be made smaller.
---

# bsp-mini: shrink a compiled GoldSrc map

All tools live in `tools/` of this repo and only need Python 3 (no third-party packages).
They edit the BSP binary directly: geometry, collision hulls, entities and texture vectors
are rescaled, lightmaps and visibility are reused unchanged.

## Workflow

1. **Inspect** the map.
   ```
   python tools/bspinfo.py MAP.bsp      # lumps, bounds, entity classes, textures
   python tools/ents.py MAP.bsp         # spawn / objective coordinates
   ```
   Note anything special: `func_tracktrain`, `func_water`, ladders, hostages, doors.

2. **Baseline** the reachability tool on the ORIGINAL map so you know what it can and
   cannot prove for this map (it does not climb ladders, and treats `func_wall` /
   `func_breakable` as solid, doors as open).
   ```
   python tools/reach.py MAP.bsp 8 stand
   python tools/reach.py MAP.bsp 8 crouch
   ```

3. **Generate candidates.** Use scale factors that are exact in float32
   (k/16: 0.375, 0.4375, 0.5, 0.5625, 0.625, 0.75, 0.8125). Start at 0.5 and go both ways.
   ```
   python tools/bspscale.py MAP.bsp out_0.5.bsp 0.5 0.5 0.5
   ```
   Read the summary line: `extent mismatches` must be 0, `size-fallback` should be 0,
   and watch for `WARNING: no free spot` (a spawn that no longer fits anywhere).

4. **Test each candidate.**
   ```
   python tools/reach.py out_0.5.bsp 8 stand     # all objectives reachable standing?
   python tools/reach.py out_0.5.bsp 8 crouch    # ... or at least crouching?
   python tools/bspcheck.py MAP.bsp out_0.5.bsp  # indices, spawns, floors
   ```
   Pick the smallest uniform scale where everything the original reaches standing is
   still reachable standing. Then check that no *area* became crouch-only, because the
   BFS will happily crouch through a low bridge or doorway on the way to an objective and
   players experience that as an invisible wall:
   ```
   python tools/reach.py out.bsp 8 stand  dump=s.json
   python tools/reach.py out.bsp 8        dump=c.json
   python tools/reachdiff.py s.json c.json 8 SX SY SZ
   ```
   Compare with the same diff on the original. Big clusters (a room, a channel) mean a
   doorway or ceiling is now under 72: measure its original height and raise Z so that
   `height * SZ > 72`. Thin one-cell strips along walls are eaves and can be ignored. If the map has low doorways or vents, uniform scaling may
   not go below ~0.75; then use a non-uniform scale (smaller XY, larger Z), e.g.
   `0.625 0.625 0.8125`, and say so explicitly in the report.

5. **Deliver** as `MAPNAME_mini.bsp` next to the original, copy `MAPNAME.txt` to
   `MAPNAME_mini.txt`, and scale the original bot mesh:
   ```
   python tools/navscale.py MAPNAME.nav MAPNAME_mini.nav SX SY SZ MAPNAME_mini.bsp
   ```
   Do not let the game auto-generate a mesh on the scaled map: it reports
   `Unconnected ladder top` for most ladders and fragments narrow ledges.

## Player size reference (GoldSrc)

| hull | size (w x d x h) | origin above feet |
|---|---|---|
| standing (hull 1) | 32 x 32 x 72 | 36 |
| crouching (hull 3) | 32 x 32 x 36 | 18 |
| step height | 18 | |
| jump | ~45 (crouch-jump ~63) | |

A passage of width W and height H is standing-passable at scale s when
`W*s > 32` and `H*s > 72`; crouch-passable when `H*s > 36`. Two more hard limits on open
maps: floor-to-sky height times s must exceed 72, and the spacing between neighbouring
spawn points times s must exceed 64: CS treats a spawn with another player within 64
units as occupied and stacks players once every spot is occupied. If the scaled spacing
is below 64, fix it with `tools/spawnspread.py IN OUT CLASS WANT` (keeps well-spaced originals, adds
spots on walkable ground near the zone) or, for a single row, `tools/bspents.py ... line`.

To strip floor weapons or other point entities: `--drop=armoury_entity`.

## Report format

- Chosen scale and why (table of scales tried vs. standing / crouching result).
- What was verified by tools and what was NOT (in-game test is always unverified).
- Anything only positionally scaled that deserves an in-game look: sprites, water,
  moving trains, explosions, ladders.

## Gotchas the tools already handle (do not re-solve)

- Clip hulls: the per-hull Minkowski expansion is removed, scaled, and re-added so the
  player does not sink into floors. Never just scale clipnode plane distances.
- Lightmaps: texture vectors are inverse-scaled and nudged per face so lightmap extents
  are bit-identical to what the original compiler wrote (inferred from the lighting lump).
- Plane count: only referenced planes are kept and deduplicated (engine limit 32767).
- Clipnode order: every node of a hull must have an index >= its head node, or the game
  dies with `PM_HullPointContents: bad node number`. `bspcheck.py` verifies this.
- Spawns are moved out of walls automatically, to a spot with a floor below and up to 8 units
  of clearance; a spawn placed exactly on a clip plane is 'stuck' in-game even though a
  point test says it is free. Hostages keep their floor-level origin.
