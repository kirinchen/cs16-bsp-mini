"""Graft the brush entities of one compiled GoldSrc BSP into another, without recompiling the target.

Build the new objects (stairs, crates, ...) as brush entities (func_wall, func_illusionary, ...) in a
small .map, compile it with sdHLT, then graft: every submodel of DONOR (*1, *2, ...) is appended to
TARGET with its own hull-0 tree, faces, lightmaps and player hulls 1-3, and DONOR's brush entities are
added to TARGET's entity lump pointing at the new models. TARGET's own geometry, lighting and
visibility stay byte-identical, so a map that looks right keeps looking right.

Textures are matched by name against TARGET's texture lump (case-insensitive); a texture TARGET does
not have is an error. The engine draws a brush entity when its bounding box touches a visible leaf of
the world, so a grafted object is culled like any other func_wall. Its lightmap is DONOR's: light the
donor .map like the target (same light_environment) so it does not stand out.

usage: python bspgraft.py TARGET.bsp DONOR.bsp OUT.bsp
"""
import re
import struct
import sys

FMT = {1: '<3ffi', 3: '<3f', 5: '<i2h3h3hHH', 6: '<8fii', 7: '<HHiHH4Bi', 9: '<i2h', 10: '<ii3h3hHH4B',
       11: '<H', 12: '<HH', 13: '<i', 14: '<3f3f3f4iiii'}


def read(path):
    d = open(path, 'rb').read()
    assert struct.unpack_from('<i', d, 0)[0] == 30, path + ': not a v30 BSP'
    L = [struct.unpack_from('<ii', d, 4 + 8 * i) for i in range(15)]
    lumps = {}
    for i, fmt in FMT.items():
        sz = struct.calcsize(fmt)
        o, l = L[i]
        lumps[i] = [list(struct.unpack_from(fmt, d, o + sz * k)) for k in range(l // sz)]
    raw = {i: d[L[i][0]:L[i][0] + L[i][1]] for i in range(15)}
    return d, raw, lumps


def texnames(raw):
    t = raw[2]
    n, = struct.unpack_from('<i', t, 0)
    offs = struct.unpack_from('<%di' % n, t, 4)
    return [t[o:o + 16].split(b'\0')[0].decode('latin1').lower() if o >= 0 else '' for o in offs]


def main():
    tgt, dnr, out = sys.argv[1:4]
    td, traw, T = read(tgt)
    dd, draw, D = read(dnr)
    tnames = texnames(traw)
    dnames = texnames(draw)
    off = {i: len(T[i]) for i in FMT}
    light_off = len(traw[8])

    T[1] += D[1]                                            # planes
    T[3] += D[3]                                            # vertices
    T[12] += [[a + off[3], b + off[3]] for a, b in D[12]]   # edges
    T[13] += [[se + off[12] if se >= 0 else se - off[12]] for (se,) in D[13]]
    for ti in D[6]:                                         # texinfo: miptex by name
        name = dnames[ti[8]]
        if name not in tnames:
            sys.exit('texture %s is not in %s' % (name, tgt))
        T[6].append(ti[:8] + [tnames.index(name), ti[9]])
    for f in D[7]:                                          # faces
        T[7].append([f[0] + off[1], f[1], f[2] + off[13], f[3], f[4] + off[6]] + f[5:9]
                    + [f[9] + light_off if f[9] >= 0 else -1])
    T[11] += [[m + off[7]] for (m,) in D[11]]               # marksurfaces

    def leaf(i):                                            # leaf 0 is the shared solid leaf
        return 0 if i == 0 else i - 1 + off[10]
    for lf in D[10][1:]:
        T[10].append([lf[0], -1] + lf[2:8] + [lf[8] + off[11], lf[9]] + lf[10:])

    def child(c):
        return c + off[5] if c >= 0 else -1 - leaf(-1 - c)
    for n in D[5]:
        T[5].append([n[0] + off[1], child(n[1]), child(n[2])] + n[3:9] + [n[9] + off[7], n[10]])
    for c in D[9]:
        T[9].append([c[0] + off[1]] + [x + off[9] if x >= 0 else x for x in c[1:3]])
    first_new = len(T[14])
    for m in D[14][1:]:
        T[14].append(m[:9] + [m[9] + off[5]] + [h + off[9] if h >= 0 else h for h in m[10:13]] + [0, m[14] + off[7], m[15]])

    for i, lim in ((1, 32767), (5, 32767), (9, 32767), (10, 32767), (14, 1024)):
        assert len(T[i]) <= lim, 'lump %d over the engine limit: %d' % (i, len(T[i]))

    # entities: DONOR's brush entities, renumbered
    ents = traw[0].split(b'\0')[0].decode('latin1').rstrip()
    add = []
    for blk in re.findall(r'\{[^}]*\}', draw[0].split(b'\0')[0].decode('latin1')):
        m = re.search(r'"model"\s+"\*(\d+)"', blk)
        if m:
            add.append(blk.replace(m.group(0), '"model" "*%d"' % (first_new + int(m.group(1)) - 1)))
    ents = ents + '\n' + '\n'.join(add) + '\n'

    lumps = {i: b''.join(struct.pack(FMT[i], *r) for r in T[i]) for i in FMT}
    lumps[0] = ents.encode('latin1') + b'\0'
    lumps[2] = traw[2]
    lumps[4] = traw[4]
    lumps[8] = traw[8] + draw[8]
    body = bytearray(td[:4] + b'\0' * 120)
    for i in range(15):
        while len(body) % 4:
            body += b'\0'
        struct.pack_into('<ii', body, 4 + 8 * i, len(body), len(lumps[i]))
        body += lumps[i]
    open(out, 'wb').write(bytes(body))
    print('grafted', len(D[14]) - 1, 'models (*%d..*%d),' % (first_new, len(T[14]) - 1), len(add), 'entities,',
          len(D[7]), 'faces,', len(D[9]), 'clipnodes ->', out)


if __name__ == '__main__':
    main()
