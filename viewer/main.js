import * as THREE from 'three';
import { parseBSP, buildRenderData, faceVertices, faceNormal, parseVec, textureColor, mapStats } from './bsp.js';

// GoldSrc is Z-up (x forward, y left); three.js is Y-up. (x, y, z) -> (x, z, -y) is a proper rotation.
const g2t = (v) => new THREE.Vector3(v[0], v[2], -v[1]);
const t2g = (v) => [v.x, -v.z, v.y];

const $ = (s) => document.querySelector(s);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);
document.body.prepend(renderer.domElement);
const camera = new THREE.PerspectiveCamera(70, 1, 4, 32768);
const scene = new THREE.Scene();
let mapGroup = null;

const state = { name: '', url: null, bsp: null, rd: null, worldMeshes: [], markers: [], selection: null, overlay: null };

// ---------- camera: fly mode, angles in GoldSrc convention (yaw around Z from +X, pitch up positive)
const cam = { pos: [0, 0, 0], yaw: 0, pitch: 0, speed: 500 };
const keys = new Set();

function applyCamera() {
  const cp = Math.cos(cam.pitch), f = [cp * Math.cos(cam.yaw), cp * Math.sin(cam.yaw), Math.sin(cam.pitch)];
  camera.position.copy(g2t(cam.pos));
  camera.lookAt(g2t([cam.pos[0] + f[0], cam.pos[1] + f[1], cam.pos[2] + f[2]]));
}

function setCamera(x, y, z, yawDeg, pitchDeg) {
  cam.pos = [x, y, z];
  cam.yaw = yawDeg * Math.PI / 180;
  cam.pitch = Math.max(-89, Math.min(89, pitchDeg)) * Math.PI / 180;
  applyCamera();
}

function initialCamera(bsp) {
  const pick = (cls) => bsp.entities.filter((e) => e.classname === cls).map((e) => parseVec(e.origin)).filter(Boolean);
  let pts = pick('info_player_start');
  if (!pts.length) pts = pick('info_player_deathmatch');
  const m = bsp.models[0];
  const center = [0, 1, 2].map((k) => (m.mins[k] + m.maxs[k]) / 2);
  const target = pts.length ? [0, 1, 2].map((k) => pts.reduce((a, p) => a + p[k], 0) / pts.length) : center;
  // stand behind the spawn (as seen from the map centre), up high, looking down at it
  let dx = center[0] - target[0], dy = center[1] - target[1];
  const len = Math.hypot(dx, dy) || 1;
  dx /= len; dy /= len;
  const size = Math.max(m.maxs[0] - m.mins[0], m.maxs[1] - m.mins[1]);
  const back = Math.min(Math.max(size * 0.22, 300), 900), up = back * 0.9;
  const pos = [target[0] - dx * back, target[1] - dy * back, target[2] + up];
  setCamera(pos[0], pos[1], pos[2], Math.atan2(dy, dx) * 180 / Math.PI, -Math.atan2(up, back) * 180 / Math.PI + 8);
}

let drag = null;
renderer.domElement.addEventListener('pointerdown', (e) => {
  drag = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
  renderer.domElement.setPointerCapture(e.pointerId);
});
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 4) drag.moved = true;
  if (!drag.moved) return;
  cam.yaw -= dx * 0.004;
  cam.pitch = Math.max(-1.55, Math.min(1.55, cam.pitch - dy * 0.004));
  applyCamera();
});
renderer.domElement.addEventListener('pointerup', (e) => {
  if (drag && !drag.moved) pickAt(e.clientX, e.clientY);
  drag = null;
});
renderer.domElement.addEventListener('wheel', (e) => {
  e.preventDefault();
  cam.speed = Math.max(50, Math.min(5000, cam.speed * Math.pow(1.15, -Math.sign(e.deltaY))));
}, { passive: false });
addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'r' && !e.repeat) { reload(); return; }
  if (k === 'p' && !e.repeat) { copyCameraParam(); return; }
  if (k === 'escape') { clearSelection(); return; }
  keys.add(k);
  if (e.shiftKey) keys.add('shift');
});
addEventListener('keyup', (e) => { keys.delete(e.key.toLowerCase()); if (!e.shiftKey) keys.delete('shift'); });
addEventListener('blur', () => keys.clear());

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  const fwd = [Math.cos(cam.pitch) * Math.cos(cam.yaw), Math.cos(cam.pitch) * Math.sin(cam.yaw), Math.sin(cam.pitch)];
  const right = [Math.sin(cam.yaw), -Math.cos(cam.yaw), 0];
  const mv = [0, 0, 0];
  const add = (v, s) => { for (let i = 0; i < 3; i++) mv[i] += v[i] * s; };
  if (keys.has('w')) add(fwd, 1);
  if (keys.has('s')) add(fwd, -1);
  if (keys.has('d')) add(right, 1);
  if (keys.has('a')) add(right, -1);
  if (keys.has('e') || keys.has(' ')) add([0, 0, 1], 1);
  if (keys.has('q')) add([0, 0, 1], -1);
  if (mv.some((x) => x)) {
    const s = cam.speed * (keys.has('shift') ? 3 : 1) * dt;
    for (let i = 0; i < 3; i++) cam.pos[i] += mv[i] * s;
    applyCamera();
  }
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

function resize() {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();
requestAnimationFrame(frame);

// ---------- world
const vertexShader = `
attribute vec2 tuv;
attribute vec2 luv;
varying vec2 vTuv;
varying vec2 vLuv;
void main() {
  vTuv = tuv; vLuv = luv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;
const fragmentShader = `
uniform sampler2D map;
uniform sampler2D lightmap;
uniform bool hasMap;
uniform vec3 baseColor;
uniform float opacity;
varying vec2 vTuv;
varying vec2 vLuv;
void main() {
  vec4 c = hasMap ? texture2D(map, vTuv) : vec4(baseColor, 1.0);
  // no pixels (texture lives in a WAD): faint checker, one tile per texture repeat, as a scale cue
  if (!hasMap) c.rgb *= 1.0 - 0.045 * mod(floor(vTuv.x) + floor(vTuv.y), 2.0);
  if (c.a < 0.5) discard;
  vec3 lm = texture2D(lightmap, vLuv).rgb;
  // GoldSrc lightmaps are stored dark and brightened by the engine's gamma tables
  lm = pow(lm, vec3(0.6)) * 1.25;
  gl_FragColor = vec4(c.rgb * lm, opacity);
}`;

function buildWorld(bsp, rd) {
  const group = new THREE.Group();
  const lmTex = new THREE.DataTexture(rd.atlas.data, rd.atlas.width, rd.atlas.height, THREE.RGBAFormat);
  lmTex.magFilter = THREE.LinearFilter;
  lmTex.minFilter = THREE.LinearFilter;
  lmTex.needsUpdate = true;
  const meshes = [];
  for (const g of rd.groups) {
    const tex = bsp.textures[g.miptex] || { name: '', pixels: null };
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(g.pos.length);
    for (let i = 0; i < g.pos.length; i += 3) { pos[i] = g.pos[i]; pos[i + 1] = g.pos[i + 2]; pos[i + 2] = -g.pos[i + 1]; }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('tuv', new THREE.BufferAttribute(new Float32Array(g.uv), 2));
    geo.setAttribute('luv', new THREE.BufferAttribute(new Float32Array(g.luv), 2));
    geo.setIndex(g.idx);
    geo.computeBoundingSphere();
    let map = null;
    if (tex.pixels) {
      map = new THREE.DataTexture(tex.pixels, tex.width, tex.height, THREE.RGBAFormat);
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      map.magFilter = THREE.LinearFilter;
      map.minFilter = THREE.LinearMipmapLinearFilter;
      map.generateMipmaps = true;
      map.anisotropy = 4;
      map.needsUpdate = true;
    }
    const water = tex.name.startsWith('!');
    const mat = new THREE.ShaderMaterial({
      vertexShader, fragmentShader, side: THREE.FrontSide, transparent: water, depthWrite: !water,
      uniforms: { map: { value: map }, lightmap: { value: lmTex }, hasMap: { value: !!map },
        baseColor: { value: new THREE.Color(...textureColor(tex.name)) }, opacity: { value: water ? 0.7 : 1 } },
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.triFace = g.triFace;
    group.add(mesh);
    meshes.push(mesh);
  }
  return { group, meshes };
}

// ---------- entity markers
const MARKER = {
  info_player_start: { color: 0x3b82f6, size: [32, 32, 72], label: 'CT' },
  info_player_deathmatch: { color: 0xef4444, size: [32, 32, 72], label: 'T' },
  info_bomb_target: { color: 0xf97316, size: [48, 48, 48] },
  armoury_entity: { color: 0xeab308, size: [24, 24, 10], floor: true },
  hostage_entity: { color: 0x22c55e, size: [32, 32, 72], floor: true },
};
const ZONE = {
  func_buyzone: { color: 0x22c55e, label: (e) => (e.team === '1' ? 'T BUY' : e.team === '2' ? 'CT BUY' : 'BUY ZONE') },
  func_bomb_target: { color: 0xf97316, label: () => 'BOMB SITE' },
  func_hostage_rescue: { color: 0x22c55e, label: () => 'RESCUE' },
};

function labelSprite(text, color) {
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  ctx.font = '600 44px ui-sans-serif, system-ui, sans-serif';
  c.width = Math.ceil(ctx.measureText(text).width) + 40;
  c.height = 64;
  ctx.font = '600 44px ui-sans-serif, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(12,15,19,0.78)';
  ctx.beginPath(); ctx.roundRect(0, 0, c.width, c.height, 14); ctx.fill();
  ctx.fillStyle = '#' + color.toString(16).padStart(6, '0');
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 20, 34);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  // constant on-screen size (sizeAttenuation off: scale is in clip-space units)
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true, sizeAttenuation: false }));
  const h = 0.03;
  sp.scale.set(h * c.width / c.height, h, 1);
  sp.renderOrder = 10;
  return sp;
}

function buildMarkers(bsp) {
  const group = new THREE.Group();
  const pickables = [];
  bsp.entities.forEach((e, ei) => {
    const cls = e.classname || '';
    const spec = MARKER[cls];
    const o = parseVec(e.origin);
    if (spec && o) {
      const [sx, sy, sz] = spec.size;
      const mat = new THREE.MeshBasicMaterial({ color: spec.color, transparent: true, opacity: 0.85 });
      const box = new THREE.Mesh(new THREE.BoxGeometry(sx, sz, sy), mat);
      const center = spec.floor ? [o[0], o[1], o[2] + sz / 2] : o;
      box.position.copy(g2t(center));
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry),
        new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35 }));
      box.add(edges);
      const ang = parseVec(e.angles) || [0, +(e.angle || 0), 0];
      if (spec.label) {
        // facing nub at eye height
        const nub = new THREE.Mesh(new THREE.BoxGeometry(14, 6, 6), mat);
        const yaw = ang[1] * Math.PI / 180;
        nub.position.copy(g2t([Math.cos(yaw) * (sx / 2 + 6), Math.sin(yaw) * (sx / 2 + 6), sz / 2 - 12]));
        nub.rotation.y = yaw;
        box.add(nub);
      }
      box.userData = { entity: ei, baseColor: spec.color, edges };
      group.add(box);
      pickables.push(box);
      return;
    }
    const zone = ZONE[cls];
    const mm = /^\*(\d+)$/.exec(e.model || '');
    if (zone && mm && bsp.models[+mm[1]]) {
      const m = bsp.models[+mm[1]];
      const off = parseVec(e.origin) || [0, 0, 0];
      const mins = m.mins.map((v, k) => v + off[k]), maxs = m.maxs.map((v, k) => v + off[k]);
      const size = [0, 1, 2].map((k) => maxs[k] - mins[k]);
      const center = [0, 1, 2].map((k) => (mins[k] + maxs[k]) / 2);
      const geo = new THREE.BoxGeometry(size[0], size[2], size[1]);
      const fill = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: zone.color, transparent: true, opacity: 0.07, depthWrite: false }));
      fill.position.copy(g2t(center));
      fill.raycast = () => {};
      fill.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: zone.color, transparent: true, opacity: 0.5 })));
      group.add(fill);
      const sp = labelSprite(zone.label(e), zone.color);
      sp.position.copy(g2t([center[0], center[1], maxs[2] + 16]));
      sp.userData = { entity: ei, zone: true, mins, maxs, model: mm[1] };
      group.add(sp);
      pickables.push(sp);
    }
  });
  return { group, pickables };
}

// ---------- picking + locator
const raycaster = new THREE.Raycaster();
const fmt = (n) => (Math.round(n * 10) / 10).toString();
const vec = (v) => `(${v.map(fmt).join(', ')})`;
const nrm = (v) => `(${v.map((x) => +(Math.round(x * 1000) / 1000)).join(',')})`;

function entityLabel(ei) {
  return `${state.bsp.entities[ei].classname || '?'}#${ei}`;
}

function entityLocator(ei, info = {}) {
  const e = state.bsp.entities[ei];
  const parts = [`map=${state.name}`, `entity=${entityLabel(ei)}`];
  if (e.origin) parts.push(`origin=${vec(parseVec(e.origin) || [0, 0, 0])}`);
  if (info.zone) parts.push(`model=*${info.model}`, `mins=${vec(info.mins)}`, `maxs=${vec(info.maxs)}`);
  if (e.angles || e.angle !== undefined) parts.push(`angles=${e.angles || `0 ${e.angle} 0`}`);
  if (e.team) parts.push(`team=${e.team}`);
  if (e.targetname) parts.push(`targetname=${e.targetname}`);
  return parts.join(' | ');
}

function faceLocator(fi, hit) {
  const { bsp, rd } = state;
  const ti = bsp.texinfo[bsp.faces[fi].texinfo];
  const mi = rd.faceModel[fi];
  const parts = [`map=${state.name}`, `pos=${vec(t2g(hit))}`, `face=${fi}`,
    `tex=${(bsp.textures[ti.miptex] || {}).name || '?'}`, `model=${mi}`, `normal=${nrm(faceNormal(bsp, fi))}`];
  if (mi > 0 && rd.modelEntity[mi] >= 0) parts.push(`entity=${entityLabel(rd.modelEntity[mi])}`);
  return parts.join(' | ');
}

function clearSelection() {
  if (state.overlay) { scene.remove(state.overlay); state.overlay.traverse((o) => o.geometry && o.geometry.dispose()); state.overlay = null; }
  for (const m of state.markers) {
    if (m.isSprite) { m.material.color.set(0xffffff); continue; }
    m.material.color.set(m.userData.baseColor); m.material.opacity = 0.85;
    m.userData.edges.material.opacity = 0.35;
  }
  state.selection = null;
}

function selectEntity(ei) {
  clearSelection();
  const m = state.markers.find((x) => x.userData.entity === ei);
  if (m) {
    if (m.isSprite) m.material.color.set(0xfff2b0);
    else {
      m.material.color.set(0xf5c542);
      m.material.opacity = 1;
      m.userData.edges.material.opacity = 1;
    }
  }
  state.selection = { entity: ei };
  return m;
}

function selectFace(fi) {
  clearSelection();
  const { bsp, rd } = state;
  const mi = rd.faceModel[fi];
  const off = rd.drawModels.get(mi) || [0, 0, 0];
  const n = faceNormal(bsp, fi);
  const pts = faceVertices(bsp, fi).map((p) => g2t([p[0] + off[0] + n[0] * 0.5, p[1] + off[1] + n[1] * 0.5, p[2] + off[2] + n[2] * 0.5]));
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  const idx = [];
  for (let k = 1; k < pts.length - 1; k++) idx.push(0, k + 1, k);
  geo.setIndex(idx);
  const fill = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0xf5c542, transparent: true, opacity: 0.35, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
  fill.add(new THREE.LineLoop(geo, new THREE.LineBasicMaterial({ color: 0xffe08a })));
  fill.renderOrder = 5;
  scene.add(fill);
  state.overlay = fill;
  state.selection = { face: fi };
}

function pickAt(x, y) {
  if (!state.bsp) return null;
  const r = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1), camera);
  const sprites = raycaster.intersectObjects(state.markers.filter((m) => m.isSprite), false);
  const hits = sprites.length ? sprites : raycaster.intersectObjects([...state.markers.filter((m) => !m.isSprite), ...state.worldMeshes], false);
  if (!hits.length) { clearSelection(); return null; }
  const h = hits[0];
  let loc;
  if (h.object.userData.entity !== undefined) {
    selectEntity(h.object.userData.entity);
    loc = entityLocator(h.object.userData.entity, h.object.userData);
  } else {
    const fi = h.object.userData.triFace[h.faceIndex];
    selectFace(fi);
    loc = faceLocator(fi, h.point);
  }
  copyText(loc);
  toast('Locator copied', loc);
  return loc;
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).catch(() => copyFallback(text));
  } else copyFallback(text);
}

function copyFallback(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); } catch { /* nothing else to try */ }
  ta.remove();
}

function copyCameraParam() {
  const s = `cam=${cam.pos.map((v) => Math.round(v)).join(',')},${Math.round(cam.yaw * 180 / Math.PI)},${Math.round(cam.pitch * 180 / Math.PI)}`;
  copyText(s);
  toast('Camera copied', s);
}

let toastTimer = 0;
function toast(title, body) {
  $('#toast .title').textContent = title;
  $('#toast .body').textContent = body;
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 7000);
}

// ---------- loading
function load(buffer, name, keepCamera) {
  const bsp = parseBSP(buffer);
  const rd = buildRenderData(bsp);
  const prevSel = state.selection;
  clearSelection();
  if (mapGroup) {
    scene.remove(mapGroup);
    mapGroup.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        for (const u of Object.values(o.material.uniforms || {})) if (u.value && u.value.isTexture) u.value.dispose();
        if (o.material.map) o.material.map.dispose();
        o.material.dispose();
      }
    });
  }
  const world = buildWorld(bsp, rd);
  const markers = buildMarkers(bsp);
  mapGroup = new THREE.Group();
  mapGroup.add(world.group, markers.group);
  scene.add(mapGroup);
  Object.assign(state, { name, bsp, rd, worldMeshes: world.meshes, markers: markers.pickables });
  const st = mapStats(bsp);
  $('#hud .name').textContent = name;
  $('#hud .stats').textContent = `${st.faces} faces · ${st.entities} entities · ${st.models} models`;
  $('#empty').style.display = 'none';
  document.title = `${name} · BSP viewer`;
  if (!keepCamera) {
    const c = new URLSearchParams(location.search).get('cam');
    const v = c && c.split(',').map(Number);
    if (v && v.length === 5 && v.every(Number.isFinite)) setCamera(...v);
    else initialCamera(bsp);
  }
  if (prevSel && prevSel.entity !== undefined && prevSel.entity < bsp.entities.length) selectEntity(prevSel.entity);
  document.body.dataset.ready = String(Date.now());
}

async function loadUrl(url, keepCamera = false) {
  const bust = url + (url.includes('?') ? '&' : '?') + '_=' + Date.now();
  const res = await fetch(bust, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${url}`);
  state.url = url;
  load(await res.arrayBuffer(), decodeURIComponent(url.split('/').pop().split('?')[0]), keepCamera);
}

async function reload() {
  if (!state.url) { toast('Reload', state.bsp ? 'Reload needs ?map=<url>; a dropped file cannot be re-read.' : 'No map loaded.'); return; }
  try {
    await loadUrl(state.url, true);
    toast('Reloaded', state.name);
  } catch (err) { toast('Reload failed', String(err.message || err)); }
}

async function loadFile(file) {
  try {
    state.url = null;
    load(await file.arrayBuffer(), file.name, false);
  } catch (err) { toast('Cannot open', String(err.message || err)); }
}

$('#open').addEventListener('click', () => $('#file').click());
$('#reload').addEventListener('click', () => reload());
$('#file').addEventListener('change', (e) => e.target.files[0] && loadFile(e.target.files[0]));
addEventListener('dragover', (e) => { e.preventDefault(); document.body.classList.add('dragging'); });
addEventListener('dragleave', (e) => { if (!e.relatedTarget) document.body.classList.remove('dragging'); });
addEventListener('drop', (e) => {
  e.preventDefault();
  document.body.classList.remove('dragging');
  const f = e.dataTransfer.files[0];
  if (f) loadFile(f);
});

const mapParam = new URLSearchParams(location.search).get('map');
if (mapParam) loadUrl(mapParam).catch((err) => toast('Cannot load map', String(err.message || err)));

// hooks for scripted screenshots / tests
window.viewer = { state, cam, setCamera, pickAt, selectEntity, entityLocator, reload, loadUrl,
  project: (g) => { const v = g2t(g).project(camera); return [(v.x + 1) / 2 * innerWidth, (1 - v.y) / 2 * innerHeight, v.z]; } };
