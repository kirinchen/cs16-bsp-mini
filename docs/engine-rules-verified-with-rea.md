# Engine rules behind the mini maps, verified in the shipped binaries with REA

The scaler and spawn tools rely on three behaviours of the Counter-Strike 1.6 engine that
were first worked out from memory of the SDK sources. They were then checked against the
shipped Steam binaries with [REA](https://github.com/morluto/rea) 6.5.0 driving Ghidra 12.1.4
(`rea search`, `rea search-bytes`, `rea read-bytes`, `rea function`). All three hold; one
detail was wrong.

| rule the tools depend on | where | verdict |
|---|---|---|
| every clipnode of a hull must have an index between the hull's first and last clipnode, or the game aborts with `PM_HullPointContents: bad node number` | `hw.dll` `FUN_101e20e0` | confirmed |
| a spawn point is "occupied" when `FindEntityInSphere(spot, 64)` returns a player; when every spot is occupied the game spawns anyway and damages whoever is in that sphere | `mp.dll` `FUN_10096190` (EntSelectSpawnPoint), `FUN_10098620` (IsSpawnPointValid) | confirmed; the damage is **200**, not the 300 assumed earlier |
| `FindEntityInSphere` measures the distance from the point to the entity's bounding box, so two spots need more than 64 + 16 = 80 units | `hw.dll` `FUN_101e4530` (table slot 16 of the engine function table at `0x1031d500`) | confirmed |
| the collision hulls the engine traces a player through are expanded by (16, 16, 36) standing, (32, 32, 32) large and (16, 16, 18) crouching, in every model | `hw.dll` `FUN_1023f060` (`Mod_LoadBrushModel`, stores at `0x1023f905`-`0x1023f9f8`) | confirmed (2026-10-21) |

Binaries: `hw.dll` sha256 (see REA evidence), `cstrike/dlls/mp.dll`
sha256 `6467586318f408b04b2eb0700cb8a8577f146f6124fd2c26a404ad0e4528c723`.

## 1. PM_HullPointContents (hw.dll 0x101e20e0)

```c
int FUN_101e20e0(int *hull, int num, float *p)
{
  if (hull->lastclipnode <= hull->firstclipnode) return -1;
  while (true) {
    if (num < 0) return num;                                   // leaf contents
    if ((num < hull->firstclipnode) || (hull->lastclipnode < num)) break;
    ... plane test, num = children[side] ...
  }
  Sys_Error("PM_HullPointContents: bad node number");
}
```

This is why `bspscale.py` writes each hull's clipnode tree in pre-order (root first) and
`bspcheck.py` reports any node index below its head node.

## 2. EntSelectSpawnPoint / IsSpawnPointValid (mp.dll)

`IsSpawnPointValid` (0x10098620), `0x42800000` is the float 64.0:

```c
if (pSpot->IsTriggered(pPlayer)) {
  for (ent = UTIL_FindEntityInSphere(NULL, pSpot->origin, 64.0); ent; ent = UTIL_FindEntityInSphere(ent, pSpot->origin, 64.0))
    if (ent->IsPlayer() && ent != pPlayer) return 0;
  return 1;
}
return 0;
```

`EntSelectSpawnPoint` (0x10096190) walks `info_player_start` (CT) or `info_player_deathmatch`
(T) until a valid spot is found; if none is, it takes the last spot and, for every player in
the same 64-unit sphere, calls `TakeDamage(world, world, 200.0, 0)` (`0x43480000` = 200.0).

## 3. PF_FindEntityInSphere (hw.dll 0x101e4530)

Found by reading the engine function table that `LoadThisDll` hands to the game DLL's
`GiveFnptrsToDll` (table at `0x1031d500`, `pfnFindEntityInSphere` is slot 16):

```c
dist2 = 0;
for (axis = 0; axis < 3 && dist2 <= rad * rad; axis++) {
  v = org[axis];
  if (v < absmin[axis])      d = v - absmin[axis];
  else if (v > absmax[axis]) d = v - absmax[axis];
  else                       d = 0;
  dist2 += d * d;
}
if (dist2 <= rad * rad) return ent;
```

A standing player's box is origin +-(16, 16, 36), so a spot 80 units away horizontally is
still "within 64" of a player standing on the neighbouring spot. `spawnspread.py` therefore
spaces spots by this box distance (default 80).

## 4. Hull sizes in Mod_LoadBrushModel (hw.dll 0x1023f060)

Added 2026-10-21 while fixing the "player stands half inside a wall" bug in `bspscale.py`: undoing
and re-applying the compiler's hull expansion depends on these exact box sizes, so they were read
out of the engine rather than assumed from the SDK. The function is the brush-model loader (it
checks for BSP version 29 / 30 and aborts with `MOD_LoadBmodel: funny lump size`); after the
clipnode lump it fills the three hull records of every model with immediates:

```c
hull[1].clip_mins = (-16, -16, -36);  hull[1].clip_maxs = (16, 16, 36);   // 0xc1800000 0xc2100000 ...
hull[2].clip_mins = (-32, -32, -32);  hull[2].clip_maxs = (32, 32, 32);   // 0xc2000000
hull[3].clip_mins = (-16, -16, -18);  hull[3].clip_maxs = (16, 16, 18);   // 0xc1900000 = -18.0
```

(`0x41800000` = 16.0, `0x42100000` = 36.0, `0x42000000` = 32.0, `0x41900000` = 18.0.) These are
the `HULLS` table in `bspscale.py`, `reachlib.py` and `spawnspread.py`.

What REA could not tell us, and what the bug actually was: the compiler offsets each brush face
by `|nx|*16 + |ny|*16 + |nz|*36` along the *face* normal, but the plane lump stores canonical
normals, so the stored distance is `d + e` for a wall whose solid side is behind the plane and
`d - e` when it is in front. The old scaler assumed `d + e` everywhere; for the other half of the
walls the expansion cancelled out exactly at scale 1/2 and hull 1 coincided with the drawn wall.
`bspcheck.py` now probes 8 units in front of every visible wall face and reports any face where
the standing or crouching hull is empty there. Two follow-ups the same check surfaced: a bevel
plane of a slanted brush is a real face of the expanded hull but only one hull width wide, so
the solid side has to come from exact portal fragments rather than point samples; and scaling
shrinks the gaps between brushes while the expansion stays 16, so a scaled brush can poke
through a split plane it used to stay clear of (by up to `2e(1-s)`), which the scaler repairs by
re-inserting those slivers into the far subtree. Result on the seven mini maps (faces where a
player could sink into a visible wall, before -> after): aztec 454 -> 0 / 2291, assault 467 -> 0 /
1278, inferno 869 -> 0 / 3635, survivor 345 -> 1 / 1945, airstrip 583 -> 1 / 3678 (clipnode limit
reached, 32765 / 32767), awp_map 55 -> 0 / 258, vertigo 805 -> 0 / 2710. The originals score 0,
except de_airstrip itself (1 / 3704).

`hw.dll` sha256 `9ba9a2db5e07598fd59afa35507a98c86162e4e15b3835177b78c11842cd2295`.

## Reproducing

```
npm install --global rea-agents
set GHIDRA_INSTALL_DIR=<extracted Ghidra 12.1.x>
rea search    mp.dll info_player_start --provider ghidra
rea search-bytes mp.dll 60550d10 --provider ghidra        # code referencing that string
rea function  mp.dll 0x10096190 --provider ghidra --format md
rea search    hw.dll "bad node number" --provider ghidra
rea function  hw.dll 0x101e20e0 --provider ghidra --format md
rea read-bytes hw.dll 0x1031d500 --length 80 --provider ghidra
rea function  hw.dll 0x101e4530 --provider ghidra --format md
rea search-bytes hw.dll 000010c2 --provider ghidra           # -36.0; the one .text hit is in FUN_1023f060
rea function  hw.dll 0x1023f060 --provider ghidra --format md
```

Each CLI call relaunches Ghidra headless (about 90 s on this machine); the MCP server mode
keeps the session open.
