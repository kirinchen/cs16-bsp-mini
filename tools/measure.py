import struct, sys, re
from collections import defaultdict
d=open(sys.argv[1],'rb').read()
L=[struct.unpack_from('<ii',d,4+8*i) for i in range(15)]
def arr(i,fmt,size): o,l=L[i]; return [struct.unpack_from(fmt,d,o+size*k) for k in range(l//size)]
verts=arr(3,'<3f',12); edges=arr(12,'<2H',4); surfedges=[x[0] for x in arr(13,'<i',4)]
texinfo=arr(6,'<8f2i',40); faces=arr(7,'<HHiHHBBBBi',20)
o,l=L[2]; nt,=struct.unpack_from('<i',d,o); offs=struct.unpack_from(f'<{nt}i',d,o+4)
names=[d[o+t:o+t+16].split(b'\0')[0].decode('latin1') for t in offs]
def facepts(f):
    fe,ne=f[2],f[3]; pts=[]
    for k in range(ne):
        se=surfedges[fe+k]; e=edges[abs(se)]; v=e[0] if se>=0 else e[1]; pts.append(verts[v])
    return pts
bytex=defaultdict(list)
for f in faces:
    nm=names[texinfo[f[4]][8]]
    bytex[nm].append(facepts(f))
pat=re.compile(sys.argv[2],re.I)
for nm,fl in bytex.items():
    if pat.search(nm):
        print("==",nm,len(fl),"faces")
        for pts in fl[:40]:
            xs=[p[0] for p in pts];ys=[p[1] for p in pts];zs=[p[2] for p in pts]
            print("   size",(max(xs)-min(xs),max(ys)-min(ys),max(zs)-min(zs)),"at",(min(xs),min(ys),min(zs)))
