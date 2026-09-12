import struct, sys
LUMPS=["ENTITIES","PLANES","TEXTURES","VERTICES","VISIBILITY","NODES","TEXINFO","FACES","LIGHTING","CLIPNODES","LEAVES","MARKSURFACES","EDGES","SURFEDGES","MODELS"]
def info(path):
    d=open(path,'rb').read()
    ver,=struct.unpack_from('<i',d,0)
    lumps=[struct.unpack_from('<ii',d,4+8*i) for i in range(15)]
    print(path, "version",ver)
    for n,(o,l) in zip(LUMPS,lumps): print(f"  {n:12s} off={o:8d} len={l:8d}")
    # models
    o,l=lumps[14]
    n=l//64
    print("  models:",n)
    for i in range(min(n,3)):
        m=struct.unpack_from('<6f3f4i i i',d,o+64*i)
        print("   model",i,"mins",m[0:3],"maxs",m[3:6],"faces",m[13],m[14] if len(m)>14 else '')
    # vertices bounds
    o,l=lumps[3]; nv=l//12
    xs=[];ys=[];zs=[]
    for i in range(nv):
        x,y,z=struct.unpack_from('<3f',d,o+12*i); xs.append(x);ys.append(y);zs.append(z)
    print("  verts",nv,"bounds",(min(xs),min(ys),min(zs)),(max(xs),max(ys),max(zs)))
    # entities
    o,l=lumps[0]; ents=d[o:o+l].decode('latin1')
    print("  entities len",l)
    import re
    classes=re.findall(r'"classname" "([^"]+)"',ents)
    from collections import Counter
    print("  classes:",Counter(classes).most_common(40))
    # worldspawn
    ws=ents[:ents.find('}')]
    print(ws)
    # textures
    o,l=lumps[2]; nt,=struct.unpack_from('<i',d,o)
    offs=struct.unpack_from(f'<{nt}i',d,o+4)
    names=[]
    for to in offs:
        if to<0: continue
        nm=d[o+to:o+to+16].split(b'\0')[0].decode('latin1'); w,h=struct.unpack_from('<II',d,o+to+16); off1,=struct.unpack_from('<I',d,o+to+24)
        names.append((nm,w,h,off1!=0))
    print("  textures",nt,"embedded",sum(1 for n in names if n[3]))
    print("  ",[n[0] for n in names][:200])
for p in sys.argv[1:]: info(p)
