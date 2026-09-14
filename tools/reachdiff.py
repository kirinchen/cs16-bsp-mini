"""cluster cells reachable crouching but not standing; print in ORIGINAL map coordinates
usage: python reachdiff.py stand.json crouch.json grid sx sy sz"""
import json,sys
from collections import deque
st=set(map(tuple,json.load(open(sys.argv[1])))); cr=set(map(tuple,json.load(open(sys.argv[2]))))
G=int(sys.argv[3]); sx,sy,sz=map(float,sys.argv[4:7])
stxy={(c[0],c[1]) for c in st}
only={(c[0],c[1]) for c in cr}-stxy
print("crouch-only cells:",len(only))
seen=set(); clusters=[]
for c in only:
    if c in seen: continue
    q=deque([c]); seen.add(c); cl=[]
    while q:
        x,y=q.popleft(); cl.append((x,y))
        for dx in(-1,0,1):
            for dy in(-1,0,1):
                n=(x+dx,y+dy)
                if n in only and n not in seen: seen.add(n); q.append(n)
    clusters.append(cl)
clusters.sort(key=len,reverse=True)
for cl in clusters[:12]:
    xs=[c[0]*G/sx for c in cl]; ys=[c[1]*G/sy for c in cl]
    zs=[c[2]/sz for c in cr if (c[0],c[1]) in set(cl)]
    print(f"  {len(cl):5d} cells  orig x {min(xs):.0f}..{max(xs):.0f}  y {min(ys):.0f}..{max(ys):.0f}  feet z {min(zs):.0f}..{max(zs):.0f}")
