/* Self-test: the NixOS enrolment the panel prints (Nodes → a new node → Declarative) works on a STOCK NixOS as printed.
 *
 * Followed literally on a fresh NixOS 26.05 box (1.8.7 qualification PART 4, A1), it failed three ways:
 *   · step ③ opened with `sudo git init …` — a stock NixOS has no git ("sudo: git: command not found");
 *   · it declared no `udpPortRanges`, and NixOS filters INPUT by default while every port the node serves is picked by the
 *     panel at run time: an interface created from the panel synced, reported healthy, and no client ever handshook (a
 *     laptop client passed the moment the range was declared) — with no node issue to say why;
 *   · the README's example range left out the system mesh band, so the node's own mesh link raised a firewall issue.
 * And `nixos-25.11` stood in the flake with nothing telling a 26.05 reader it is a whole-OS change.
 *
 *   [1] every step-③ command runs on a stock NixOS: `git` only behind a test that /etc/nixos IS a git repository
 *   [2] both arms declare udpPortRanges, and the ranges cover what the panel actually hands out on a fresh node — the port
 *       suggestPort offers a new interface and a new turn server, qWDTT's RAW port 56003, and the whole mesh band as
 *       swg-panel-server reserves it (read from its source, not restated here)
 *   [3] the band follows the panel's settings: a different reserved band moves the declared range
 *   [4] the nixpkgs line says to use the channel `nixos-version` prints
 *
 * Run: node tests/spa_nixsteps_selftest.mjs          (0 = pass)
 *      --perturb       prints the snippet without its udpPortRanges line again, and expects RED on [2]
 *      --perturb-git   restores the unconditional `sudo git init`, and expects RED on [1]
 */
import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const PERTURB_GIT = process.argv.includes("--perturb-git");

const PANEL = readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
const mBase = Number(/"mesh_port_base":\s*(\d+)/.exec(PANEL)?.[1]);
const mSpan = Number(/"port_span":\s*(\d+)/.exec(PANEL)?.[1]);
check("the mesh band is READABLE from swg-panel-server", Number.isInteger(mBase) && mBase > 0 && Number.isInteger(mSpan) && mSpan > 0, `${mBase}/${mSpan}`);

let S;
if (PERTURB || PERTURB_GIT) {
  let src = readFileSync(path.join(ROOT, "js", "sheets-crud.js"), "utf8");
  const [from, to] = PERTURB
    ? [/\n    ports,\n/g, "\n"]
    : [/"\[ -d \/etc\/nixos\/\.git \] && sudo git -C \/etc\/nixos add flake\.nix[^"]*"/g, '"cd /etc/nixos && sudo git init -q -b main && sudo git add -A"'];
  const n = (src.match(from) || []).length;
  if (n !== 2) { console.log(`PERTURB FAILED — the anchor matched ${n} times, not 2 (one per arm)`); process.exit(1); }
  src = src.replace(from, to);
  // a sibling of the real module (relative imports keep working) — never left behind: removed right after import
  const tmp = path.join(ROOT, "js", ".perturb_sheets_crud.mjs");
  writeFileSync(tmp, src);
  try { S = await import(pathToFileURL(tmp).href); } finally { try { unlinkSync(tmp); } catch (_) { /* gone */ } }
} else {
  S = await spa("sheets-crud.js");
}
const M = await spa("model.js");
const { Store } = await spa("store.js");
check("[0] nixNodeSteps is exported", typeof S.nixNodeSteps === "function");

Store.panelSettings = { reserved: { mesh_port_base: mBase, port_span: mSpan } };
const RSV = Store.panelSettings.reserved;
const firstIface = M.suggestPort("fresh-node", "iface");
const firstTurn = M.suggestPort("fresh-node", "turn");

const parseRanges = flake => {
  const m = /udpPortRanges = \[(.*?)\];/.exec(flake);
  if (!m) return null;
  return [...m[1].matchAll(/\{ from = (\d+); to = (\d+); \}/g)].map(x => [Number(x[1]), Number(x[2])]);
};
const covers = (rs, p) => !!rs && rs.some(([a, b]) => a <= p && p <= b);

for (const arm of ["native", "podman"]) {
  const steps = S.nixNodeSteps("https://panel.example.org:8443", "203.0.113.10", "TOKEN", false, arm, RSV);
  const flake = (steps[1] || [])[1] || "", build = (steps[2] || [])[1] || "";
  // [1]
  const lines = build.split("\n").map(l => l.replace(/\s+#.*$/, "").trim()).filter(Boolean);
  const bad = lines.filter(l => /\bgit\b/.test(l) && !/^\[ -d \/etc\/nixos\/\.git \] && /.test(l));
  check(`[1] ${arm}: step ③ runs git only on a git-tracked /etc/nixos`, lines.length >= 2 && !bad.length, bad);
  check(`[1] ${arm}: …and still rebuilds with the flake`, lines.some(l => l === "sudo nixos-rebuild switch --flake /etc/nixos#swg"), lines);
  // [2]
  const rs = parseRanges(flake);
  check(`[2] ${arm}: the flake declares udpPortRanges`, !!rs && rs.length > 0, flake);
  check(`[2] ${arm}: …covering the first interface port the panel suggests (${firstIface})`, covers(rs, firstIface), rs);
  check(`[2] ${arm}: …the first turn-server port it suggests (${firstTurn})`, covers(rs, firstTurn), rs);
  check(`[2] ${arm}: …qWDTT's RAW port 56003`, covers(rs, 56003), rs);
  check(`[2] ${arm}: …and the whole mesh band ${mBase}–${mBase + mSpan - 1}`, covers(rs, mBase) && covers(rs, mBase + mSpan - 1), rs);
  // [4]
  check(`[4] ${arm}: the nixpkgs line says to use this box's own channel`, /inputs\.nixpkgs\.url[^\n]*#[^\n]*nixos-version/.test(flake), flake.split("\n")[1]);
}
// [3]
const moved = S.nixNodeSteps("https://p", "203.0.113.10", "T", false, "native", { mesh_port_base: 20000, port_span: 50 });
const mr = parseRanges(moved[1][1]);
check("[3] a different reserved band moves the declared mesh range", covers(mr, 20000) && covers(mr, 20049) && !covers(mr, mBase), mr);

done(PERTURB || PERTURB_GIT, PERTURB ? "udpPortRanges dropped" : "unconditional git init");
