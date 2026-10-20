// Cross-check the JS BSP reader against the Python tools.
// usage: node viewer/test/parse.mjs MAP.bsp [MAP.bsp ...]
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseBSP, buildRenderData } from '../bsp.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const tools = path.join(root, 'tools');
let failed = 0;

function check(label, ok, detail = '') {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? '  ' + detail : ''}`);
  if (!ok) failed++;
}

function py(code) {
  return execFileSync('python3', ['-c', code], { cwd: tools, encoding: 'utf8', maxBuffer: 64 << 20 });
}

for (const map of process.argv.slice(2).map((m) => path.resolve(m))) {
  console.log('==', path.basename(map));
  const buf = readFileSync(map);
  const bsp = parseBSP(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length));

  // face count: bspinfo.py prints the FACES lump length (20 bytes per face)
  const info = execFileSync('python3', [path.join(tools, 'bspinfo.py'), map], { encoding: 'utf8' });
  const facesLen = +/FACES\s+off=\s*\d+\s+len=\s*(\d+)/.exec(info)[1];
  check('faces', bsp.faces.length === facesLen / 20, `js=${bsp.faces.length} bspinfo=${facesLen / 20}`);
  const nModels = +/models: (\d+)/.exec(info)[1];
  check('models', bsp.models.length === nModels, `js=${bsp.models.length} bspinfo=${nModels}`);

  // entity order and keys: tools/bspents.py read() + blocks() + kv(), the same walk `dump` prints
  const p = JSON.stringify(map);
  const pyEnts = JSON.parse(py(`import json, bspents\nd, L, e = bspents.read(${p})\nprint(json.dumps([bspents.kv(b) for b in bspents.blocks(e)]))`));
  check('entity count', bsp.entities.length === pyEnts.length, `js=${bsp.entities.length} bspents=${pyEnts.length}`);
  const firstDiff = pyEnts.findIndex((e, i) => JSON.stringify(e) !== JSON.stringify(bsp.entities[i]));
  check('entity #n order + keys', firstDiff < 0, firstDiff < 0 ? '' : `first mismatch at #${firstDiff}`);

  // spawns: tools/ents.py ents()
  const pySp = JSON.parse(py(`import json, sys\nsys.argv = ['x']\nimport ents\nE = ents.ents(${p})\nprint(json.dumps({c: [e.get('origin', '') for e in E if e.get('classname') == c] for c in ('info_player_start', 'info_player_deathmatch')}))`));
  for (const cls of ['info_player_start', 'info_player_deathmatch']) {
    const js = bsp.entities.filter((e) => e.classname === cls).map((e) => e.origin || '');
    check(`${cls} origins`, JSON.stringify(js) === JSON.stringify(pySp[cls]), `${js.length} spawns, first ${js[0]}`);
  }

  // dump line n == entity #n
  const dump = execFileSync('python3', [path.join(tools, 'bspents.py'), map, 'dump'], { encoding: 'utf8' }).trim().split('\n');
  const ct = bsp.entities.findIndex((e) => e.classname === 'info_player_start');
  check(`dump line ${ct} is info_player_start`, dump[ct].includes("'classname': 'info_player_start'") && dump[ct].includes(bsp.entities[ct].origin));

  const rd = buildRenderData(bsp);
  const tris = rd.groups.reduce((a, g) => a + g.triFace.length, 0);
  console.log(`  render: ${rd.faceList.length} faces drawn, ${tris} triangles, ${rd.groups.length} textures, ` +
    `lightmap atlas ${rd.atlas.width}x${rd.atlas.height} (${rd.atlas.blocks.size} blocks), ` +
    `${bsp.textures.filter((t) => t.pixels).length} embedded textures`);
  check('lightmap blocks for most faces', rd.atlas.blocks.size > rd.faceList.length * 0.8);
}
console.log(failed ? `${failed} check(s) failed` : 'all checks passed');
process.exit(failed ? 1 : 0);
