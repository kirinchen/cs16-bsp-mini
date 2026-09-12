# goldsrc-bsp-mini

Shrink a compiled GoldSrc / Counter-Strike 1.6 map (`.bsp`) into a playable "mini" version
**without decompiling or recompiling**. Pure Python 3, no dependencies.

`de_dust2_mini` style maps, for any map, in seconds:

| map | scale | fully walkable standing |
|---|---|---|
| de_aztec | 1/2 | yes |
| de_inferno | 1/2 | yes |
| de_survivor | 7/16 | yes |
| de_airstrip | 9/16 | yes |
| cs_assault | XY 5/8, Z 13/16 | yes (vents need crouch, as in the original) |

Everything shrinks together: geometry, collision hulls, textures, entity positions.
Lighting and visibility are reused from the original compile, so the result looks like the
original map, just smaller.

## Quick start

```
python tools/bspscale.py de_aztec.bsp de_aztec_mini.bsp 0.5 0.5 0.5
python tools/reach.py    de_aztec_mini.bsp 8 stand
python tools/bspcheck.py de_aztec.bsp de_aztec_mini.bsp
```

Drop `de_aztec_mini.bsp` into `cstrike/maps/` and `map de_aztec_mini`.
Bots regenerate the `.nav` on first load.

Use scale factors that are exact in binary (multiples of 1/16: 0.375, 0.4375, 0.5, 0.5625,
0.625, 0.75, 0.8125) so vertex coordinates carry no rounding error. Non-uniform scales are
allowed (`SX SY SZ`), useful for maps with low doorways.

## Tools

| tool | purpose |
|---|---|
| `tools/bspscale.py IN OUT SX SY SZ` | the scaler |
| `tools/reach.py MAP [grid] [stand]` | BFS a player-sized box from T spawn to CT spawn and objectives using the map's own collision hulls; reports what is reachable standing / crouching |
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
  expansion, scales, and adds it back, per hull, then deduplicates planes (engine limit 32767).
- **Entities**: `MaxRange`, door `lip`, `func_tracktrain` wheels/speed, `bombradius`,
  `env_explosion` magnitude are scaled. Everything else is left alone.

Not handled: lightmap resampling (not needed with this approach), `.nav` files, and
anything that only exists in the game code (weapon ranges, fall damage).

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
