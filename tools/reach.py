"""Reachability check: BFS a player-sized box over a grid using the BSP collision hulls.
usage: python reach.py map.bsp [grid=8] [stand] [dump=cells.json]
  grid  : XY sample spacing in units (8 is a good default; smaller is slower)
  stand : only use the standing hull; default allows crouching too
  dump= : write the reachable cell set to a JSON file (for reachdiff.py)
"""
import struct, sys, re
from collections import deque
path=sys.argv[1]; G=int(sys.argv[2]) if len(sys.argv)>2 else 8
d=open(path,'rb').read(); L=[struct.unpack_from('<ii',d,4+8*i) for i in range(15)]
def arr(i,fmt):
    sz=struct.calcsize(fmt); o,l=L[i]; return [struct.unpack_from(fmt,d,o+sz*k) for k in range(l//sz)]
planes=arr(1,'<3ffi'); clip=arr(9,'<ihh'); models=arr(14,'<3f3f3f4iiii')
o,l=L[0]; ents=[dict(re.findall(r'"([^"]*)" "([^"]*)"',b)) for b in re.findall(r'\{([^}]*)\}',d[o:o+l].decode('latin1'))]
SOLID_CLS={'func_wall','func_breakable','func_button','func_train','func_tracktrain','func_pushable'}
solid_models=[int(e['model'][1:]) for e in ents if e.get('classname') in SOLID_CLS and e.get('model','').startswith('*')]
PASS={-1,-3,-16}
def segs(hull,model,x,y,z0,z1):
    """passable z-intervals along vertical line in given hull"""
    out=[]
    stack=[(models[model][9+hull],z0,z1)]
    while stack:
        n,a,b=stack.pop()
        if a>=b: continue
        if n<0:
            if n in PASS: out.append((a,b))
            continue
        pn,c1,c2=clip[n]; nx,ny,nz,dist,_=planes[pn]
        base=nx*x+ny*y-dist
        if abs(nz)<1e-9:
            stack.append((c1 if base>=0 else c2,a,b)); continue
        zs=-base/nz
        if zs<=a: stack.append((c1 if nz>0 else c2,a,b))
        elif zs>=b: stack.append((c2 if nz>0 else c1,a,b))
        else:
            # below zs: f<0 if nz>0 -> back(c2)
            stack.append(((c2 if nz>0 else c1),a,zs)); stack.append(((c1 if nz>0 else c2),zs,b))
    out.sort()
    merged=[]
    for a,b in out:
        if merged and a<=merged[-1][1]+1e-6: merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else: merged.append((a,b))
    return merged
def blocked(hull,x,y,a,b):
    """subtract solid brush-model intervals"""
    ivs=[(a,b)]
    for m in solid_models:
        mm=models[m]
        if not(mm[0]-40<=x<=mm[3]+40 and mm[1]-40<=y<=mm[4]+40): continue
        free=segs(hull,m,x,y,a,b)  # passable inside model hull
        new=[]
        for ia,ib in ivs:
            for fa,fb in free:
                lo,hi=max(ia,fa),min(ib,fb)
                if hi>lo: new.append((lo,hi))
        ivs=new
    return ivs
HULLS=((1,36),) if "stand" in sys.argv[3:] else ((1,36),(3,18))
OFFS=[(0,0),(G/2,0),(-G/2,0),(0,G/2),(0,-G/2),(G/2,G/2),(-G/2,-G/2),(G/2,-G/2),(-G/2,G/2)]
ZMIN,ZMAX=models[0][2]-64,models[0][5]+64
cache={}
def spots(cx,cy):
    """list of (feet_z, hull) standable spots at cell"""
    if (cx,cy) in cache: return cache[(cx,cy)]
    res=[]; seen_z=set()
    for ox,oy in OFFS:
        x,y=cx*G+ox,cy*G+oy
        for hull,half in HULLS:
            for a,b in segs(hull,0,x,y,ZMIN,ZMAX):
                for ia,ib in blocked(hull,x,y,a,b):
                    key=(round((ia-half)/4),hull)
                    if ib-ia>1 and key not in seen_z: seen_z.add(key); res.append((ia-half,hull))
    cache[(cx,cy)]=res; return res
def near_spot(p):
    cx,cy=round(p[0]/G),round(p[1]/G); best=None
    for dx in range(-3,4):
        for dy in range(-3,4):
            for fz,h in spots(cx+dx,cy+dy):
                dd=abs(fz-(p[2]-36))+ (dx*dx+dy*dy)*G
                if best is None or dd<best[0]: best=(dd,(cx+dx,cy+dy,fz,h))
    return best[1] if best else None
def bfs(start,JUMP=45):
    seen={start}; q=deque([start])
    while q:
        cx,cy,fz,h=q.popleft()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(0,0)):
            for fz2,h2 in spots(cx+dx,cy+dy):
                if fz2-fz<=JUMP and (dx or dy or h2!=h) :
                    if (dx==0 and dy==0) and abs(fz2-fz)>JUMP: continue
                    n=(cx+dx,cy+dy,fz2,h2)
                    if n not in seen: seen.add(n); q.append(n)
    return seen
def origin(e): return tuple(float(t) for t in e['origin'].split())
T=[origin(e) for e in ents if e.get('classname')=='info_player_deathmatch']
CT=[origin(e) for e in ents if e.get('classname')=='info_player_start']
goals={'CT spawn':CT[0],'T spawn':T[0]}
for e in ents:
    if e.get('classname') in('func_bomb_target','hostage_entity','func_hostage_rescue'):
        if e.get('model','').startswith('*'):
            m=models[int(e['model'][1:])]; goals[e['classname']+e['model']]=((m[0]+m[3])/2,(m[1]+m[4])/2,m[2]+36)
        else: goals[e['classname']+e.get('origin','')]=origin(e)
start=near_spot(T[0]); print("start",start)
seen=bfs(start)
cells={(c[0],c[1]) for c in seen}
print("reachable spots",len(seen),"cells",len(cells))
for name,p in goals.items():
    sp=near_spot(p); ok=sp in seen
    if not ok and sp:  # maybe another spot in same cell
        ok=any(c[0]==sp[0] and c[1]==sp[1] and abs(c[2]-sp[2])<40 for c in seen)
    print(f"  {name:32s} {'REACHABLE' if ok else 'NOT reachable'}  {sp}")
print("both-spawn reachable:",all(near_spot(p) in seen for p in T+CT))
for a in sys.argv[3:]:
    if a.startswith('dump='):
        import json; json.dump(sorted(set((c[0],c[1],round(c[2])) for c in seen)),open(a[5:],'w'))
