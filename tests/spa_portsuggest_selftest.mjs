/* Self-test: the port a create sheet PRE-FILLS must be one the server will accept.
 *
 * `suggestPort` seeds from `Math.max(...ifacePorts) + 1`. On a freshly-enrolled node the only interfaces
 * ARE the mesh links, so the seed lands one above the highest mesh port — inside the band the server
 * refuses outright ("port N is in the reserved system mesh range"). Found on hel-flux during 1.8.5
 * qualification: "Create new interface" offered :10002 and Create answered that its own default was
 * invalid. That is the first thing a new operator does on a new node.
 *
 * ⚠️ TWO READERS, ONE GRAMMAR — and the readers are in different LANGUAGES. The suggester is JS, the
 * validator is Python, and each carries its own fallback for the band. A gate that only drove the JS side
 * would stay green while the server moved its defaults, so the band is read OUT OF `swg-panel-server`'s
 * source here and the SPA is required to agree with it.
 *
 * Run: node tests/spa_portsuggest_selftest.mjs
 *      --perturb   restores the seed and skip-set that knew nothing about the band, and expects RED.
 */
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");

// ── the band, read from the SERVER, not restated here ────────────────────────────────────────────────
const PANEL = readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
const mBase = Number(/"mesh_port_base":\s*(\d+)/.exec(PANEL)?.[1]);
const mSpan = Number(/"port_span":\s*(\d+)/.exec(PANEL)?.[1]);
check("the band is READABLE from swg-panel-server (a silent 0 here would pass everything)",
      Number.isInteger(mBase) && mBase > 0 && Number.isInteger(mSpan) && mSpan > 0, `${mBase}/${mSpan}`);

const { Store } = await spa("store.js");
const model = await spa("model.js");
let suggestPort = model.suggestPort;

if (PERTURB) {
  // The shipped behaviour: seed off EVERY interface port, skip only the upstream defaults.
  const src = readFileSync(path.join(ROOT, "js", "model.js"), "utf8");
  const before = src;
  const patched = src
    .replace("const mineUser = mine.filter(q => !inMesh(q));", "const mineUser = mine;")
    .replace("while ((used.has(p) || reserved.has(p) || inMesh(p)) && p < 65535) p++;",
             "while ((used.has(p) || reserved.has(p)) && p < 65535) p++;");
  if (patched === before) { console.log("PERTURB ANCHOR MISSING — this run would FALSE-PASS"); process.exit(1); }
  // Written BESIDE the real module so its own relative imports resolve exactly as they do in the browser.
  // (A data: URL cannot resolve "./i18n.js", and rewriting the specifiers by regex silently missed the one
  // with a digit in it — a perturbation that crashes reads the same as one that was caught.)
  const tmp = path.join(ROOT, "js", ".perturbed-model.mjs");
  writeFileSync(tmp, patched);
  try {
    suggestPort = (await import(pathToFileURL(tmp).href)).suggestPort;
  } finally {
    unlinkSync(tmp);
  }
}

// A node exactly as it looks the moment it finishes enrolling: three mesh links, no user interface.
const meshOnly = { interfaces: {
  swg_aaaa: { meta: { listen_port: mBase + 1 } },
  swg_bbbb: { meta: { listen_port: mBase + 2 } },
  swg_cccc: { meta: { listen_port: mBase + 3 } } } };
Store.stats = { n1: meshOnly, n2: { interfaces: {} },
                n3: { interfaces: { ...meshOnly.interfaces, wg0: { meta: { listen_port: 51821 } } } } };
Store.panelSettings = { reserved: { mesh_port_base: mBase, port_span: mSpan } };

const inBand = p => p >= mBase && p < mBase + mSpan;

console.log("\n[1] a freshly-enrolled node must not be offered a port its own server refuses");
const p1 = suggestPort("n1", "iface");
check("mesh-only node: the suggestion is OUTSIDE the reserved band", !inBand(p1), `suggested ${p1}`);
check("…and it is the documented default, not an arbitrary port above the band", p1 === 51821, `suggested ${p1}`);

console.log("\n[2] a mesh link does not get a vote on where the next USER interface starts");
const p0 = suggestPort("n2", "iface");
check("a node with no interfaces at all suggests 51821", p0 === 51821, p0);
check("a mesh-only node suggests the SAME thing — the mesh is invisible here", p1 === p0, `${p1} vs ${p0}`);

console.log("\n[3] real user interfaces still drive the sequence");
const p3 = suggestPort("n3", "iface");
check("a node with wg0 on 51821 suggests 51822", p3 === 51822, p3);

console.log("\n[4] the band is avoided wherever the operator puts it");
Store.panelSettings = { reserved: { mesh_port_base: 51820, port_span: 10 } };
const p4 = suggestPort("n2", "iface");
check("a band moved onto the default start pushes the suggestion past it",
      p4 >= 51830 && p4 < 65535, `suggested ${p4}`);
Store.panelSettings = { reserved: { mesh_port_base: mBase, port_span: mSpan } };

console.log("\n[5] the turn family is seeded from its own ports and is unaffected");
check("a turn suggestion on a mesh-only node is still 56002", suggestPort("n1", "turn") === 56002,
      suggestPort("n1", "turn"));

done(PERTURB, "the band-unaware seed and skip-set");
