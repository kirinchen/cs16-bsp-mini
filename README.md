# goldsrc-agent-kit

Edit compiled GoldSrc maps (Counter-Strike 1.6, Half-Life, TFC, DoD) by talking to an AI agent:
shrink a whole map, move spawns, check collision, preview and pick in 3D in the browser.
The agent works on the compiled `.bsp` directly; every engine rule the tools rely on is
checked in the shipped binaries (see *Engine rules, verified*). Formerly `cs16-bsp-mini`.

## Shrinking a map

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
| `tools/spawnspread.py IN OUT CLASS WANT [MIN_BOX] [REACH]` | keep or add spawn points of a team so that WANT of them exist with a spot-to-player-box distance of at least MIN_BOX (default 80; the engine refuses a spot with a player box within 64), placed on walkable ground near the existing spawn zone |
| `tools/reachlib.py` | the walkability model shared by reach.py and spawnspread.py |
| `tools/bspmove.py MAP ENT DX DY DZ [OUT]` | move one entity (index #n as in `bspents.py dump` and the 3D viewer's locator) by an offset; only its `origin` key changes, every other byte stays |
| `tools/bspents.py MAP dump [class]` / `IN OUT line CLASS X Z Y0 Y1` | inspect entities, or re-space all spawns of a class evenly along a line (CS refuses a spawn with another player within 64 units, so shrunken spawn rows need re-spacing) |
| `tools/bspdecomp.py MAP.bsp OUT.map [wads]` | decompile an axis-aligned map to a Valve-220 .map (exact round trip on box maps); also a library for building .map files from code |
| `tools/navscale.py IN.nav OUT.nav SX SY SZ [scaled.bsp]` | scale a CS 1.6 bot navigation mesh (v5) to match the scaled map; keeps connections, hiding spots, place names |
| `tools/reachdiff.py stand.json crouch.json grid sx sy sz` | cluster the cells reachable only crouching and print them in original-map coordinates, so you can see which doorway or ceiling forces the crouch |
| `tools/bspcheck.py ORIG SCALED [x y z ...]` | index-range check, clipnode order, every spawn in open air with a floor below, **hull-vs-wall check** (a player centre 8 units in front of every visible wall must be solid in hull 1 and 3, otherwise players sink into that wall), optional point probes |
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
  expansion, scales, and adds it back, per hull. Which *way* a plane was expanded is not stored
  (normals are canonical, so a wall with its solid on the plane's front side is stored as
  `d - e`, one with the solid behind as `d + e`): the scaler finds the solid side of every
  clipnode by clipping the node's portal polygon down both child subtrees and voting by area.
  Getting this wrong cancels the expansion at scale 1/2 and lets players stand half inside
  walls (454 of 2291 wall faces on the first de_aztec_mini). Scaling also shrinks the gaps
  between brushes but not the expansion, so a scaled brush can poke through a split plane it
  used to stay clear of; those slivers are re-inserted into the far subtree as convex brushes
  (deepest first, up to the engine's 32767-clipnode limit). Subtrees the compiler shared
  between hulls are split per hull and written in pre-order, because the engine refuses any
  clipnode whose index is below its hull's head node (`PM_HullPointContents: bad node number`).
- **Entities**: `MaxRange`, door `lip`, `func_tracktrain` wheels/speed, `bombradius`,
  `env_explosion` magnitude are scaled. Everything else is left alone.

Not handled: lightmap resampling (not needed with this approach) and anything that only
exists in the game code (weapon ranges, fall damage).

## 3D viewer

`viewer/` is a static browser preview and picker for BSP v30 files (three.js from a pinned CDN
URL, no build step). Click a spawn or a wall and it copies a one-line *locator* you can paste to
an agent ("move this spawn back 64"); the agent edits the BSP with the tools above and you press
**R** to see the result.

```sh
ln -s /path/to/your/maps viewer/maps   # gitignored; the server only sees files under the repo
#   Windows: mklink /J viewer\maps C:\path\to\your\maps
python3 -m http.server 8000          # from the repo root
# open http://localhost:8000/viewer/?map=maps/de_aztec_mini.bsp
```

Or open `http://localhost:8000/viewer/` and drop a .bsp on the page / use **Open .bsp** (reload
only works for `?map=`). `?cam=x,y,z,yaw,pitch` sets the start camera (**P** copies the current one).

| input | action |
|---|---|
| drag | look around |
| W A S D | move; Q / E down / up; Shift faster; wheel changes speed |
| click | pick a face or entity marker, copy its locator, show it in the corner |
| R / Reload | re-fetch the same URL (cache-busted), keep the camera and selected entity |
| Esc | clear the selection |

Drawn: the world and non-trigger brush entities, shaded with the map's own lightmaps times a
colour hashed from the texture name (or the embedded texture when the BSP carries its pixels;
WAD textures are not loaded). Tool textures (`sky`, `aaatrigger`, `clip`, `origin`, `null`, ...) are
skipped. Markers: CT spawns blue, T spawns red, bomb targets, `armoury_entity`, hostages, and
labelled buy zone / bomb site / rescue volumes.

Locator formats (always GoldSrc coordinates, Z up; `#n` is the entity's index in the entity lump,
0 = worldspawn, the same order `bspents.py MAP dump` prints):

```
map=cs_assault_mini.bsp | pos=(-430, 1264.3, 127.4) | face=951 | tex=generic77 | model=0 | normal=(1,0,0)
map=de_aztec_mini.bsp | entity=info_player_start#175 | origin=(-1420, 180, -210) | angles=0 0 0
```

A face on a brush entity adds `entity=func_door#12`; a zone label adds `model=*N` and its
`mins` / `maxs`. Typical follow-up: `python3 tools/bspmove.py MAP.bsp 175 -64 0 0`.

`node viewer/test/parse.mjs MAP.bsp ...` cross-checks the JS parser against the Python tools
(face / model / entity counts, entity order, spawn origins).

**Limits.** Editing a compiled BSP can move or retarget entities, change texture names and
scale the whole map; it cannot "add a wall here". New geometry changes the BSP tree, the
collision hulls, visibility and the lightmaps, so it needs a recompile (see *Beyond scaling*
below). Moving a point entity is safe, but nothing re-checks gameplay rules: run
`tools/bspcheck.py` to make sure a moved spawn is not inside a wall, and keep spawns 64+ units
apart.

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

## Engine rules, verified

The four engine behaviours the tools depend on were checked in the shipped `hw.dll` and
`mp.dll` with REA + Ghidra: see `docs/engine-rules-verified-with-rea.md`.
