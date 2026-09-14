# Scales found for the stock CS 1.6 maps

Method: generate candidates at k/16 scales, run `reach.py` in `stand` and `crouch` mode,
take the smallest uniform scale where everything the original reaches standing is still
reachable standing.

| map | 3/8 | 7/16 | 1/2 | 9/16 | 5/8 | chosen |
|---|---|---|---|---|---|---|
| de_aztec | crouch only | crouch only | stand* | stand | stand | **XY 1/2, Z 3/4** |
| de_inferno | - | site B crouch | stand | stand | stand | **1/2** |
| de_survivor | 3 CT spawns do not fit | stand (3 spawns nudged) | stand | stand | stand | **7/16** |
| de_airstrip | - | - | crouch only | stand | stand | **9/16** |
| cs_assault | - | - | vents impassable | vents impassable | doors 72 high, crouch | **XY 5/8, Z 13/16** |

cs_assault limits: vent interior 56x56 (crouch hull 32x36 needs Z >= 0.65),
doorways 64x96 (standing hull 72 needs Z > 0.75). Non-uniform is the only way to get the
footprint down; `de_dust2_mini` itself is roughly XY 0.52, Z 0.6.

\* de_aztec at uniform 1/2 passes the reachability test, but only because the tool allows
crouching on the way: the water tunnel exit passes under the bridge, whose underside is 98
units above the water floor (49 at 1/2). Players read that as an invisible wall. Several CT
side doorways (119-128 high) also drop below 72. `reachdiff.py` finds these: it lists the
cells reachable crouching but not standing, clustered, in original coordinates. Z = 3/4
gives 73.5 under the bridge and 89+ in the doorways; what remains crouch-only are wall
eaves that are not on any route.
