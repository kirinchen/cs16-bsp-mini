// GoldSrc BSP v30 reader + render-data builder. No DOM, no three.js: runs in the browser and in node.

const LUMP = { ENTITIES: 0, PLANES: 1, TEXTURES: 2, VERTICES: 3, VISIBILITY: 4, NODES: 5, TEXINFO: 6, FACES: 7,
  LIGHTING: 8, CLIPNODES: 9, LEAVES: 10, MARKSURFACES: 11, EDGES: 12, SURFEDGES: 13, MODELS: 14 };

export const TOOL_TEXTURES = new Set(['sky', 'aaatrigger', 'clip', 'origin', 'null', 'hint', 'skip', 'bevel', 'clipbevel']);

// Brush entities that are volumes, not visible walls. They are shown as zone markers or not at all.
export const ZONE_CLASSES = new Set(['func_buyzone', 'func_bomb_target', 'func_hostage_rescue', 'func_escapezone',
  'func_vip_safetyzone', 'func_ladder']);

export function isTriggerClass(cls) {
  return cls.startsWith('trigger_') || ZONE_CLASSES.has(cls);
}

function latin1(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  return s;
}

function cstr(bytes) {
  const z = bytes.indexOf(0);
  return latin1(z < 0 ? bytes : bytes.subarray(0, z));
}

// Same parse as tools/bspents.py: text up to the first NUL, blocks `{...}`, `"key" "value"` pairs,
// later duplicates win. The array index is the entity index (#n) used by the locator and bspmove.py.
export function parseEntities(text) {
  const out = [];
  for (const m of text.matchAll(/\{[^}]*\}/g)) {
    const kv = {};
    for (const p of m[0].matchAll(/"([^"]*)" "([^"]*)"/g)) kv[p[1]] = p[2];
    out.push(kv);
  }
  return out;
}

export function parseBSP(buffer) {
  const dv = new DataView(buffer);
  const u8 = new Uint8Array(buffer);
  const version = dv.getInt32(0, true);
  if (version !== 30) throw new Error(`not a GoldSrc BSP (version ${version}, want 30)`);
  const lumps = [];
  for (let i = 0; i < 15; i++) lumps.push({ ofs: dv.getInt32(4 + 8 * i, true), len: dv.getInt32(8 + 8 * i, true) });
  const L = (i) => lumps[i];

  const ent = L(LUMP.ENTITIES);
  const entText = cstr(u8.subarray(ent.ofs, ent.ofs + ent.len));
  const entities = parseEntities(entText);

  const pl = L(LUMP.PLANES);
  const nPlanes = pl.len / 20;
  const planes = new Float32Array(nPlanes * 4);
  for (let i = 0; i < nPlanes; i++) {
    const o = pl.ofs + 20 * i;
    planes[4 * i] = dv.getFloat32(o, true);
    planes[4 * i + 1] = dv.getFloat32(o + 4, true);
    planes[4 * i + 2] = dv.getFloat32(o + 8, true);
    planes[4 * i + 3] = dv.getFloat32(o + 12, true);
  }

  const vl = L(LUMP.VERTICES);
  const vertices = new Float32Array(vl.len / 4);
  for (let i = 0; i < vertices.length; i++) vertices[i] = dv.getFloat32(vl.ofs + 4 * i, true);

  const el = L(LUMP.EDGES);
  const edges = new Uint16Array(el.len / 2);
  for (let i = 0; i < edges.length; i++) edges[i] = dv.getUint16(el.ofs + 2 * i, true);

  const sl = L(LUMP.SURFEDGES);
  const surfedges = new Int32Array(sl.len / 4);
  for (let i = 0; i < surfedges.length; i++) surfedges[i] = dv.getInt32(sl.ofs + 4 * i, true);

  const tl = L(LUMP.TEXINFO);
  const texinfo = [];
  for (let i = 0; i < tl.len / 40; i++) {
    const o = tl.ofs + 40 * i;
    const v = [];
    for (let k = 0; k < 8; k++) v.push(dv.getFloat32(o + 4 * k, true));
    texinfo.push({ s: v.slice(0, 4), t: v.slice(4, 8), miptex: dv.getInt32(o + 32, true), flags: dv.getInt32(o + 36, true) });
  }

  const tx = L(LUMP.TEXTURES);
  const textures = [];
  const nTex = tx.len ? dv.getInt32(tx.ofs, true) : 0;
  for (let i = 0; i < nTex; i++) {
    const to = dv.getInt32(tx.ofs + 4 + 4 * i, true);
    if (to < 0) { textures.push({ name: '', width: 16, height: 16, pixels: null }); continue; }
    const o = tx.ofs + to;
    const name = cstr(u8.subarray(o, o + 16));
    const width = dv.getUint32(o + 16, true), height = dv.getUint32(o + 20, true);
    const mip0 = dv.getUint32(o + 24, true), mip3 = dv.getUint32(o + 36, true);
    let pixels = null;
    if (mip0 && width && height) {
      // palette sits after the 4th mip level: u16 count + 256 RGB triples
      const pal = o + mip3 + (width >> 3) * (height >> 3) + 2;
      if (pal + 768 <= tx.ofs + tx.len) {
        const transparent = name.startsWith('{');
        pixels = new Uint8Array(width * height * 4);
        for (let p = 0; p < width * height; p++) {
          const c = u8[o + mip0 + p];
          pixels[4 * p] = u8[pal + 3 * c];
          pixels[4 * p + 1] = u8[pal + 3 * c + 1];
          pixels[4 * p + 2] = u8[pal + 3 * c + 2];
          pixels[4 * p + 3] = transparent && c === 255 ? 0 : 255;
        }
      }
    }
    textures.push({ name, width, height, pixels });
  }

  const fl = L(LUMP.FACES);
  const faces = [];
  for (let i = 0; i < fl.len / 20; i++) {
    const o = fl.ofs + 20 * i;
    faces.push({
      plane: dv.getUint16(o, true), side: dv.getUint16(o + 2, true),
      firstEdge: dv.getInt32(o + 4, true), numEdges: dv.getUint16(o + 8, true),
      texinfo: dv.getUint16(o + 10, true), styles: [u8[o + 12], u8[o + 13], u8[o + 14], u8[o + 15]],
      lightOfs: dv.getInt32(o + 16, true),
    });
  }

  const ll = L(LUMP.LIGHTING);
  const lighting = u8.subarray(ll.ofs, ll.ofs + ll.len);

  const ml = L(LUMP.MODELS);
  const models = [];
  for (let i = 0; i < ml.len / 64; i++) {
    const o = ml.ofs + 64 * i;
    const f = (k) => dv.getFloat32(o + 4 * k, true);
    models.push({ mins: [f(0), f(1), f(2)], maxs: [f(3), f(4), f(5)], origin: [f(6), f(7), f(8)],
      firstFace: dv.getInt32(o + 56, true), numFaces: dv.getInt32(o + 60, true) });
  }

  return { version, lumps, entities, planes, vertices, edges, surfedges, texinfo, textures, faces, lighting, models };
}

export function faceVertices(bsp, fi) {
  const f = bsp.faces[fi];
  const out = [];
  for (let k = 0; k < f.numEdges; k++) {
    const se = bsp.surfedges[f.firstEdge + k];
    const v = se >= 0 ? bsp.edges[2 * se] : bsp.edges[2 * -se + 1];
    out.push([bsp.vertices[3 * v], bsp.vertices[3 * v + 1], bsp.vertices[3 * v + 2]]);
  }
  return out;
}

export function faceNormal(bsp, fi) {
  const f = bsp.faces[fi];
  const n = [bsp.planes[4 * f.plane], bsp.planes[4 * f.plane + 1], bsp.planes[4 * f.plane + 2]];
  return f.side ? n.map((x) => -x) : n;
}

// Which model each face belongs to, and which entity owns each model (by "model" "*N").
export function modelOwners(bsp) {
  const faceModel = new Int32Array(bsp.faces.length).fill(-1);
  bsp.models.forEach((m, mi) => { for (let k = 0; k < m.numFaces; k++) faceModel[m.firstFace + k] = mi; });
  const modelEntity = new Int32Array(bsp.models.length).fill(-1);
  bsp.entities.forEach((e, ei) => {
    const m = /^\*(\d+)$/.exec(e.model || '');
    if (m && +m[1] < bsp.models.length) modelEntity[+m[1]] = ei;
  });
  modelEntity[0] = 0;
  return { faceModel, modelEntity };
}

export function parseVec(s) {
  const v = (s || '').trim().split(/\s+/).map(Number);
  return v.length === 3 && v.every(Number.isFinite) ? v : null;
}

// Engine-style lightmap extents: s,t computed per vertex, floor/ceil to 16-unit luxels.
function lightmapExtents(bsp, fi, verts) {
  const ti = bsp.texinfo[bsp.faces[fi].texinfo];
  const st = verts.map((p) => [
    Math.fround(p[0] * ti.s[0] + p[1] * ti.s[1] + p[2] * ti.s[2] + ti.s[3]),
    Math.fround(p[0] * ti.t[0] + p[1] * ti.t[1] + p[2] * ti.t[2] + ti.t[3])]);
  const mins = [Infinity, Infinity], maxs = [-Infinity, -Infinity];
  for (const c of st) for (let j = 0; j < 2; j++) { mins[j] = Math.min(mins[j], c[j]); maxs[j] = Math.max(maxs[j], c[j]); }
  const bmin = mins.map((x) => Math.floor(x / 16)), bmax = maxs.map((x) => Math.ceil(x / 16));
  return { st, bmin, w: bmax[0] - bmin[0] + 1, h: bmax[1] - bmin[1] + 1 };
}

// Shelf-pack every face lightmap (style 0) into one RGBA atlas. Each block gets a 1-luxel border
// copied from its edge so bilinear filtering does not bleed between neighbours.
export function buildLightmapAtlas(bsp, faceList) {
  const W = 2048;
  const blocks = new Map();
  let x = 4, y = 0, rowH = 4; // top-left 4x4 is plain white for faces without a lightmap
  const items = [];
  for (const fi of faceList) {
    const f = bsp.faces[fi];
    const ti = bsp.texinfo[f.texinfo];
    if (f.lightOfs < 0 || f.styles[0] === 255 || (ti.flags & 1)) continue;
    const verts = faceVertices(bsp, fi);
    const ext = lightmapExtents(bsp, fi, verts);
    if (ext.w > 64 || ext.h > 64 || f.lightOfs + ext.w * ext.h * 3 > bsp.lighting.length) continue;
    items.push({ fi, ext });
  }
  items.sort((a, b) => b.ext.h - a.ext.h);
  for (const it of items) {
    const bw = it.ext.w + 2, bh = it.ext.h + 2;
    if (x + bw > W) { x = 0; y += rowH; rowH = 0; }
    blocks.set(it.fi, { x: x + 1, y: y + 1, ext: it.ext });
    x += bw; rowH = Math.max(rowH, bh);
  }
  let H = 4;
  while (H < y + rowH) H *= 2;
  const data = new Uint8Array(W * H * 4);
  for (let yy = 0; yy < 4; yy++) for (let xx = 0; xx < 4; xx++) data.fill(255, 4 * (yy * W + xx), 4 * (yy * W + xx) + 4);
  for (const [fi, b] of blocks) {
    const src = bsp.faces[fi].lightOfs, { w, h } = b.ext;
    for (let j = -1; j <= h; j++) for (let i = -1; i <= w; i++) {
      const si = Math.min(Math.max(i, 0), w - 1), sj = Math.min(Math.max(j, 0), h - 1);
      const s = src + 3 * (sj * w + si), d = 4 * ((b.y + j) * W + b.x + i);
      data[d] = bsp.lighting[s]; data[d + 1] = bsp.lighting[s + 1]; data[d + 2] = bsp.lighting[s + 2]; data[d + 3] = 255;
    }
  }
  return { width: W, height: H, data, blocks };
}

function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

// Muted building-material palette for textures that live in an external WAD.
const PALETTE = [[0.62, 0.60, 0.56], [0.70, 0.64, 0.52], [0.58, 0.45, 0.38], [0.52, 0.42, 0.32], [0.55, 0.57, 0.48],
  [0.50, 0.55, 0.60], [0.66, 0.66, 0.66], [0.60, 0.52, 0.44], [0.46, 0.50, 0.46], [0.72, 0.68, 0.60]];

// Colour from the name family (letters before trailing digits), small brightness jitter from the
// full name, so AZTEC_WALL01 and AZTEC_WALL02 look related but not identical.
export function textureColor(name) {
  const n = name.toLowerCase().replace(/^[{!+~\-]+[0-9a-j]?/, '');
  const fam = n.replace(/[0-9_]+[a-z]?$/, '') || n;
  const base = PALETTE[hash(fam) % PALETTE.length];
  const k = 0.92 + (hash(n) % 100) / 625;
  return base.map((c) => Math.min(1, c * k));
}

// Collect faces to draw (world + visible brush entities, no tool textures), triangulate, and
// group by miptex. Positions stay in GoldSrc coordinates; the caller maps them to its own axes.
export function buildRenderData(bsp) {
  const { faceModel, modelEntity } = modelOwners(bsp);
  const drawModels = new Map(); // model index -> offset
  bsp.models.forEach((m, mi) => {
    if (mi === 0) { drawModels.set(0, [0, 0, 0]); return; }
    const ei = modelEntity[mi];
    if (ei < 0) return;
    const e = bsp.entities[ei];
    const cls = e.classname || '';
    if (isTriggerClass(cls)) return;
    if ((e.rendermode && e.rendermode !== '0') && e.renderamt === '0' && cls !== 'func_water') return;
    drawModels.set(mi, parseVec(e.origin) || [0, 0, 0]);
  });
  const faceList = [];
  for (const [mi] of drawModels) {
    const m = bsp.models[mi];
    for (let k = 0; k < m.numFaces; k++) {
      const fi = m.firstFace + k;
      const tex = bsp.textures[bsp.texinfo[bsp.faces[fi].texinfo].miptex];
      if (tex && TOOL_TEXTURES.has(tex.name.toLowerCase())) continue;
      faceList.push(fi);
    }
  }
  const atlas = buildLightmapAtlas(bsp, faceList);
  const groups = new Map();
  for (const fi of faceList) {
    const f = bsp.faces[fi];
    const ti = bsp.texinfo[f.texinfo];
    const tex = bsp.textures[ti.miptex] || { name: '', width: 64, height: 64 };
    const off = drawModels.get(faceModel[fi]);
    const verts = faceVertices(bsp, fi);
    if (verts.length < 3) continue;
    let g = groups.get(ti.miptex);
    if (!g) groups.set(ti.miptex, g = { miptex: ti.miptex, pos: [], uv: [], luv: [], triFace: [] });
    const block = atlas.blocks.get(fi);
    const base = g.pos.length / 3;
    for (const p of verts) {
      g.pos.push(p[0] + off[0], p[1] + off[1], p[2] + off[2]);
      const s = p[0] * ti.s[0] + p[1] * ti.s[1] + p[2] * ti.s[2] + ti.s[3];
      const t = p[0] * ti.t[0] + p[1] * ti.t[1] + p[2] * ti.t[2] + ti.t[3];
      g.uv.push(s / (tex.width || 64), t / (tex.height || 64));
      if (block) {
        g.luv.push((block.x + s / 16 - block.ext.bmin[0] + 0.5) / atlas.width,
          (block.y + t / 16 - block.ext.bmin[1] + 0.5) / atlas.height);
      } else {
        g.luv.push(2 / atlas.width, 2 / atlas.height);
      }
    }
    // GoldSrc winds faces clockwise seen from the front; emit counter-clockwise fans.
    for (let k = 1; k < verts.length - 1; k++) {
      g.idx = g.idx || [];
      g.idx.push(base, base + k + 1, base + k);
      g.triFace.push(fi);
    }
  }
  return { atlas, groups: [...groups.values()], faceList, faceModel, modelEntity, drawModels };
}

export function mapStats(bsp) {
  return { faces: bsp.faces.length, entities: bsp.entities.length, models: bsp.models.length, textures: bsp.textures.length };
}
