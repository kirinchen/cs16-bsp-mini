"""Write the textures embedded in a GoldSrc BSP to a WAD3 file, so a decompiled map can be recompiled
(pass the WAD to sdHLCSG with -wadinclude to embed them again).

usage: python bspwad.py MAP.bsp OUT.wad
"""
import struct
import sys


def embedded(path):
    d = open(path, 'rb').read()
    o, l = struct.unpack_from('<ii', d, 4 + 8 * 2)
    nt, = struct.unpack_from('<i', d, o)
    offs = struct.unpack_from('<%di' % nt, d, o + 4)
    valid = sorted(t for t in offs if t >= 0)
    out = []
    for t in offs:
        if t < 0:
            continue
        name = d[o + t:o + t + 16].split(b'\0')[0]
        mip0, = struct.unpack_from('<I', d, o + t + 24)
        if mip0 == 0:                     # name only, pixels live in an external WAD
            continue
        nxt = min([v for v in valid if v > t] + [l])
        out.append((name, d[o + t:o + nxt]))
    return out


def write_wad(path, tex):
    body = bytearray()
    entries = []
    for name, blob in tex:
        entries.append((12 + len(body), len(blob), name))
        body += blob
        body += b'\0' * (-len(body) % 4)
    info = bytearray()
    for off, size, name in entries:
        info += struct.pack('<iiibbh16s', off, size, size, 0x43, 0, 0, name[:15])
    open(path, 'wb').write(b'WAD3' + struct.pack('<ii', len(entries), 12 + len(body)) + bytes(body) + bytes(info))


if __name__ == '__main__':
    tex = embedded(sys.argv[1])
    write_wad(sys.argv[2], tex)
    print(len(tex), "textures ->", sys.argv[2], [n.decode('latin1') for n, _ in tex])
