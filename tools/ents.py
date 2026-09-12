import struct, sys, re
def ents(path):
    d=open(path,'rb').read()
    o,l=struct.unpack_from('<ii',d,4)
    txt=d[o:o+l].decode('latin1')
    out=[]
    for blk in re.findall(r'\{([^}]*)\}',txt):
        kv=dict(re.findall(r'"([^"]*)" "([^"]*)"',blk))
        out.append(kv)
    return out
for p in sys.argv[1:]:
    E=ents(p)
    print("==",p)
    for cls in ("info_player_start","info_player_deathmatch","func_bomb_target","func_buyzone","hostage_entity","func_ladder","func_door","func_door_rotating","func_button","trigger_camera"):
        pts=[e.get('origin','') for e in E if e.get('classname')==cls]
        if pts: print(cls, len(pts), pts[:6])
    # min/max of spawns

