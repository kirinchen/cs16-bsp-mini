# cs16-bsp-mini

Shrink a compiled Counter-Strike 1.6 map (`.bsp`) into a playable "mini" version
**without decompiling or recompiling**. Pure Python 3, no dependencies. Works on any
GoldSrc engine map (Half-Life, TFC, Day of Defeat) as well.

`de_dust2_mini` style maps, for any map, in seconds:

| map | scale | fully walkable standing |
|---|---|---|
| de_aztec | XY 1/2, Z 3/4 | yes (bridge underside is only 98 units high) |
| de_inferno | 1/2 | yes |
| de_survivor | 7/16 | yes |
| de_airstrip | 9/16 | yes |
| cs_assault | XY 5/8, Z 13/16 | yes (vents need crouch, as in the original) |
| awp_map | 5/16 | yes (limits: sky height 304 > 72 and spawn spacing 124 > 32) |

Everything shrinks together: geometry, collision hulls, textures, entity positions.
Lighting and visibility are reused from the original compile, so the result looks like the
original map, just smaller.

## Quick start

```
python tools/bspscale.py de_aztec.bsp de_aztec_mini.bsp 0.5 0.5 0.75
python tools/reach.py    de_aztec_mini.bsp 8 stand
python tools/bspcheck.py de_aztec.bsp de_aztec_mini.bsp
```

Drop `de_aztec_mini.bsp` into `cstrike/maps/` and `map de_aztec_mini`.

For bots, scale the original hand-tuned mesh instead of letting the game generate one on
the shrunken geometry (auto-generation leaves ladders unconnected and cuts narrow ledges
into fragments):

```
python tools/navscale.py de_aztec.nav de_aztec_mini.nav 0.5 0.5 0.75 de_aztec_mini.bsp
```

Use scale factors that are exact in binary (multiples of 1/16: 0.375, 0.4375, 0.5, 0.5625,
0.625, 0.75, 0.8125) so vertex coordinates carry no rounding error. Non-uniform scales are
allowed (`SX SY SZ`), useful for maps with low doorways.

## Tools

| tool | purpose |
|---|---|
| `tools/bspscale.py IN OUT SX SY SZ [--drop=class,class]` | the scaler; `--drop` removes point entities by classname (e.g. `armoury_entity` to strip floor weapons) |
| `tools/reach.py MAP [grid] [stand]` | BFS a player-sized box from T spawn to CT spawn and objectives using the map's own collision hulls; reports what is reachable standing / crouching |
| `tools/spawnspread.py IN OUT CLASS WANT [MIN_DIST] [REACH]` | keep or add spawn points of a team so that WANT of them exist with no two closer than MIN_DIST (default 72), placed on walkable ground near the existing spawn zone |
| `tools/bspents.py MAP dump [class]` / `IN OUT line CLASS X Z Y0 Y1` | inspect entities, or re-space all spawns of a class evenly along a line (CS refuses a spawn with another player within 64 units, so shrunken spawn rows need re-spacing) |
| `tools/bspdecomp.py MAP.bsp OUT.map [wads]` | decompile an axis-aligned map to a Valve-220 .map (exact round trip on box maps); also a library for building .map files from code |
| `tools/navscale.py IN.nav OUT.nav SX SY SZ [scaled.bsp]` | scale a CS 1.6 bot navigation mesh (v5) to match the scaled map; keeps connections, hiding spots, place names |
| `tools/reachdiff.py stand.json crouch.json grid sx sy sz` | cluster the cells reachable only crouching and print them in original-map coordinates, so you can see which doorway or ceiling forces the crouch |
| `tools/bspcheck.py ORIG SCALED [x y z ...]` | index-range check, every spawn in open air with a floor below, optional point probes |
| `tools/bspinfo.py MAP...` | lumps, bounds, entity classes, texture list |
| `tools/ents.py MAP...` | spawn / objective coordinates |
| `tools/measure.py MAP REGEX` | sizes of faces whose texture name matches (measure doors, vents) |

## How the scaler works

Direct BSP v30 lump surgery:

- **Vertices, models, node/leaf boxes, entity origins** are scaled. Player spawns keep the
  same feet-to-origin distance and are moved out of walls if the shrunken room got too tight.
- **Texture vectors** are inverse-scaled so texture coordinates stay identical, which means the
  **lightmap lump is reused as is**. Coordinates that sit exactly on a 16-unit lightmap
  boundary are nudged per face toward the extents the original compiler used (inferred from
  the lighting lump layout), so no face gets a mis-sized lightmap.
- **Clip hulls** are the tricky part. GoldSrc stores collision as planes already expanded by
  the player's half-size. Scaling those distances directly would shrink the expansion and let
  the player sink 18 units into the floor. The scaler subtracts the per-hull Minkowski
  expansion, scales, and adds it back, per hull. Subtrees the compiler shared between hulls
  are split per hull and written in pre-order, because the engine refuses any clipnode whose
  index is below its hull's head node (`PM_HullPointContents: bad node number`).
- **Entities**: `MaxRange`, door `lip`, `func_tracktrain` wheels/speed, `bombradius`,
  `env_explosion` magnitude are scaled. Everything else is left alone.

Not handled: lightmap resampling (not needed with this approach) and anything that only
exists in the game code (weapon ranges, fall damage).

## Claude Code skill

`.claude/skills/bsp-mini/SKILL.md` teaches Claude Code the full workflow
(inspect, baseline, candidates, test, deliver, report). Copy the folder to
`~/.claude/skills/bsp-mini/` to use it in any project, or open this repo directly.

## Limits of the reachability tool

`reach.py` walks a grid with step 18, jump 45, optional crouch. It treats `func_wall` and
`func_breakable` as solid and doors as open. It does not climb ladders, so run it on the
**original** map first to see what it can prove for that map, then compare.

## License

MIT. Map files are not included; they belong to Valve.

## Beyond scaling: cut, splice, recompile

`bspdecomp.py` turns an axis-aligned map back into brushes, so maps can be cut and spliced
in code and recompiled with [sdHLT](https://github.com/seedee/SDHLT).
`examples/awp_bloodstrike/merge_build.py` cuts cs_bloodstirke at y=0, pushes the halves
apart and fills the gap with awp_map_mini's octagonal cover, seam walls blocking the centre
line. Round trip check: decompile + recompile of cs_bloodstirke reproduces the same
reachable space and the same per-texture face area as the original.
