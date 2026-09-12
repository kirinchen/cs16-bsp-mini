# Scales found for the stock CS 1.6 maps

Method: generate candidates at k/16 scales, run `reach.py` in `stand` and `crouch` mode,
take the smallest uniform scale where everything the original reaches standing is still
reachable standing.

| map | 3/8 | 7/16 | 1/2 | 9/16 | 5/8 | chosen |
|---|---|---|---|---|---|---|
| de_aztec | crouch only | crouch only | stand | stand | stand | **1/2** |
| de_inferno | - | site B crouch | stand | stand | stand | **1/2** |
| de_survivor | 3 CT spawns do not fit | stand (3 spawns nudged) | stand | stand | stand | **7/16** |
| de_airstrip | - | - | crouch only | stand | stand | **9/16** |
| cs_assault | - | - | vents impassable | vents impassable | doors 72 high, crouch | **XY 5/8, Z 13/16** |

cs_assault limits: vent interior 56x56 (crouch hull 32x36 needs Z >= 0.65),
doorways 64x96 (standing hull 72 needs Z > 0.75). Non-uniform is the only way to get the
footprint down; `de_dust2_mini` itself is roughly XY 0.52, Z 0.6.
