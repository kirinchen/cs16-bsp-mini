"""Scale a CS 1.6 / Condition Zero bot navigation mesh (.nav, format version 5) to match a
map scaled with bspscale.py, so bots use the hand-tuned original mesh instead of a mesh
auto-generated on the shrunken geometry.

usage: python navscale.py in.nav out.nav SX SY SZ [scaled.bsp]

Areas, hiding spots and their heights are scaled; connections, approach and encounter data,
place names and attribute flags are kept. Ladders are not stored in v5 files (the game
rebuilds them from func_ladder entities at load). If the scaled .bsp is given, the header's
bsp-size field is updated so the game does not warn about a mismatched mesh.
"""
import struct
import sys
import os

src, dst = sys.argv[1], sys.argv[2]
SX, SY, SZ = (float(x) for x in sys.argv[3:6])
bsp_size = os.path.getsize(sys.argv[6]) if len(sys.argv) > 6 else None

d = open(src, 'rb').read()
off = 0
out = bytearray()


def rd(fmt):
    global off
    v = struct.unpack_from('<' + fmt, d, off)
    off += struct.calcsize('<' + fmt)
    return v


def wr(fmt, *vals):
    out.extend(struct.pack('<' + fmt, *vals))


def copy(n):
    global off
    out.extend(d[off:off + n])
    off += n


def vec():
    x, y, z = rd('fff')
    wr('fff', x * SX, y * SY, z * SZ)


magic, ver, size = rd('III')
assert magic == 0xFEEDFACE and ver == 5, "expected a version-5 CS 1.6 nav file"
wr('III', magic, ver, bsp_size if bsp_size else size)

nplaces = rd('H')[0]
wr('H', nplaces)
for _ in range(nplaces):
    ln = rd('H')[0]
    wr('H', ln)
    copy(ln)

nareas = rd('I')[0]
wr('I', nareas)
nspots = 0
for _ in range(nareas):
    copy(4 + 1)          # id, attribute flags
    vec()                # nw corner
    vec()                # se corner
    nez, swz = rd('ff')
    wr('ff', nez * SZ, swz * SZ)
    for _ in range(4):   # connections per direction
        n = rd('I')[0]
        wr('I', n)
        copy(4 * n)
    nh = rd('B')[0]
    wr('B', nh)
    for _ in range(nh):  # hiding spots: id, pos, flags
        copy(4)
        vec()
        copy(1)
        nspots += 1
    nap = rd('B')[0]
    wr('B', nap)
    copy(nap * (4 + 4 + 1 + 4 + 1))
    ne = rd('I')[0]
    wr('I', ne)
    for _ in range(ne):  # encounter: from, fromDir, to, toDir, spots(id, t)
        copy(4 + 1 + 4 + 1)
        ns = rd('B')[0]
        wr('B', ns)
        copy(ns * 5)
    copy(2)              # place id
# Some Valve meshes (cs_assault, de_airstrip) carry extra per-area link data after the last
# area. It holds area ids and flags only, no coordinates, so it is copied verbatim.
trailing = len(d) - off
copy(trailing)
open(dst, 'wb').write(out)
print("areas", nareas, "hiding spots", nspots, "places", nplaces, "trailing", trailing,
      "->", dst, len(out), "bytes")
