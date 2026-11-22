/* Self-test: an exit's row says which BACKUP carries its traffic while it is down (1.8.12 item 18).
 *
 * The node reports `exit_via` {exit id: the backup id carrying it, "" for none}; the panel puts it on the row as `live.via`
 * (exits_live). `exitHealth` then says where the traffic goes — through the backup by its title, instead of "this node's own
 * IP" or "the kill-switch is holding" — on every state the node routes around (stalled, recovering, down, failed); with the
 * node saying none is up, today's sentence stands and one more says the backups are down too. A row from a node that sends
 * nothing (no backups, or too old) reads exactly as before.
 *
 * …and the save paths (source: the settings screen's closures): the node's edit buffer carries `backup` (it rebuilds every
 * exit from a key list — without it the sheet opened on "No backup" for a stored list), the sheet's change test sees a backup
 * change, and a failover node's copy shows no picker (its list follows the primary's).
 *
 * Run: node tests/spa_exit_backup_selftest.mjs     --perturb  blinds `exitViaName` (no backup is ever named) and expects RED.
 *      --perturb-nfields · --perturb-dirty · --perturb-fill  take one save-path line out each (SRC_PLANTS) and expect RED.
 */
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const SRC_PLANTS = {
  "--perturb-nfields": ["...(Array.isArray(x.backup) && x.backup.length ? { backup: x.backup.map(String) } : {}),", ""],
  "--perturb-dirty": ["    || JSON.stringify(v.backup || []) !== JSON.stringify(ex.backup || []);", "    ;"],
  "--perturb-fill": ["${fill || !bkOpts.length ? null : html`<${ExitBackupPick}", "${!bkOpts.length ? null : html`<${ExitBackupPick}"],
};
const SMODE = Object.keys(SRC_PLANTS).find(k => process.argv.includes(k));
let R = await spa("routing.js");
if (PERTURB) {
  const src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
  const a = "export const exitViaName = (ex, node) => {\n  const v = String((((ex || {}).live) || {}).via || \"\");";
  if (src.split(a).length !== 2) { console.log("PERTURB ANCHOR MISSING: exitViaName"); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_exitbackup.js");
  fs.writeFileSync(tmp, src.replace(a, "export const exitViaName = (ex, node) => {\n  const v = \"\";"));
  try { R = await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
}
const { exitHealth, exitViaName } = R;
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
Store.recon.nodeStatus = { n1: "live" };

const A = { id: "a1", producer: "imported", provider: "warp", device: "wgx-a1", label: "WG WARP", enabled: true };
const B = { id: "b2", producer: "imported", provider: "warp-masque", device: "wgx-b2", label: "MASQUE", enabled: true };
const C = { id: "c3", producer: "imported", provider: "warp", device: "wgx-c3", label: "", enabled: true };
const NODE = { id: "n1", name: "n1", exits: [A, B, C] };
const row = (live, ks = false) => ({ ...A, killswitch: ks, live: { device: "wgx-a1", up: true, ...live } });
const dead = { no_traffic: { since: 1, why: "nothing crossed the tunnel" } };

console.log("[1] the backup carrying is named");
check("exitViaName: the backup's title", exitViaName(row({ ...dead, via: "b2" }), NODE) === "MASQUE");
check("…an untitled backup by its kind's name", exitViaName(row({ ...dead, via: "c3" }), NODE) === "WARP exit");
check("…nothing when the node says none, or nothing", exitViaName(row({ ...dead, via: "" }), NODE) === ""
      && exitViaName(row(dead), NODE) === "");
const st = exitHealth(row({ ...dead, via: "b2" }), NODE);
check("stalled: through its backup, by name — not this node's own IP",
      st.state === "stalled" && /through its backup, MASQUE/.test(st.why) && !/own IP/.test(st.why), st);
const stk = exitHealth(row({ ...dead, via: "b2" }, true), NODE);
check("…and not the kill-switch holding it, with the switch on", /through its backup, MASQUE/.test(stk.why)
      && !/kill-switch is holding/.test(stk.why), stk.why);
const rc = exitHealth(row({ no_traffic: { since: 1, why: "x", back_in: 30 }, via: "b2" }), NODE);
check("recovering: still carried by the backup meanwhile", rc.state === "recovering" && /through its backup, MASQUE/.test(rc.why), rc);
const dn = exitHealth(row({ up: false, via: "b2" }), NODE);
check("down: the backup carries meanwhile", dn.state === "down" && /through its backup, MASQUE/.test(dn.why), dn);
const fl = exitHealth(row({ up: false, error: "registration failed", via: "b2" }), NODE);
check("failed: the backup carries meanwhile", fl.state === "failed" && /through its backup, MASQUE/.test(fl.why), fl);

console.log("[2] none up, or a node that says nothing");
const no = exitHealth(row({ ...dead, via: "" }), NODE);
check("none up: today's sentence, and the backups said down too",
      /own IP/.test(no.why) && /backup exits are not carrying either/.test(no.why), no.why);
const old = exitHealth(row(dead), NODE);
check("no `via` at all: exactly today's row", /own IP/.test(old.why) && !/backup/.test(old.why), old.why);
const ok = exitHealth({ ...A, live: { device: "wgx-a1", up: true, trace: { ip: "1.2.3.4" }, handshake: 5 } }, NODE);
check("a healthy exit says nothing of backups", !/backup/.test(ok.why || ""), ok);

console.log("[3] the save paths");
let SET = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
if (SMODE) {
  if (SET.split(SRC_PLANTS[SMODE][0]).length !== 2) { console.log("ANCHOR MISSING: " + SRC_PLANTS[SMODE][0]); process.exit(1); }
  SET = SET.replace(SRC_PLANTS[SMODE][0], SRC_PLANTS[SMODE][1]);
}
const nf = SET.slice(SET.indexOf("exits: (n.exits || []).map(x => ({"), SET.indexOf("const [nodeEdits, setNodeEdits]"));
check("the node's edit buffer carries each imported exit's backups (or the sheet opens without them)",
      nf.includes("...(Array.isArray(x.backup) && x.backup.length ? { backup: x.backup.map(String) } : {}),"));
const sheet = SET.slice(SET.indexOf("function ExitEditSheet("), SET.indexOf("function ExitBackupPick("));
check("the sheet's change test sees a backup change", sheet.includes("JSON.stringify(v.backup || []) !== JSON.stringify(ex.backup || [])"));
check("a failover node's copy shows no picker", sheet.includes("${fill || !bkOpts.length ? null : html`<${ExitBackupPick}"));

done(PERTURB || !!SMODE, SMODE || "exitViaName blinded");
