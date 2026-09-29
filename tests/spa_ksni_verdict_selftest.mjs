/* Self-test: on KERNEL SNI a Direct or Block rule by SITE NAME runs, and its row says so (1.8.8, KSNI-HOSTNAMES D3).
 *
 * Until 1.8.8 the in-kernel scanner lowered a site name only for a rule that leaves by an exit, and the row gate said so
 * (F19, `caa11c5`): a site badge on a Direct or Block row was inert with the switch to Hybrid SNI. The node now lowers
 * Direct and Block by name itself — measured on msk-main (`ip.me → Block` refused every connection, `api.seeip.org →
 * Direct` above a catch-all exit left directly) — so the gate must stop calling those rows inert, or the panel would
 * push operators off a mode that now does what they asked. What stays gated is the one thing the kernel may still be
 * unable to do: bind a per-person row's devices (`src < 2`), for every action alike.
 *
 * Run: node tests/spa_ksni_verdict_selftest.mjs
 *      --perturb   puts the pre-1.8.8 verdict branch back into `rowGate` and expects red.
 */
import { spa, check, done, ROOT } from "./spa_env.mjs";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PERTURB = process.argv.includes("--perturb");
let R;
if (PERTURB) {
  const src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
  const a = "  if (!(row && row.who) || ((((Store.stats || {})[node] || {}).smartroute || {}).src || 0) >= 2) return g;\n";
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING: the per-person line the old branch sat above"); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_ksni_verdict.js");
  fs.writeFileSync(tmp, src.replace(a, '  if (row && (row.action === "direct" || row.action === "block")) return { ok: false, why: "ksni_verdict", fix: "sni" };\n' + a));
  try { R = await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
} else {
  R = await spa("routing.js");
}
const { rowGate, rulesSummary, PATTERN_ENGINE_OK, MODE_META } = R;
const { Store } = await spa("store.js");
const { classify } = await spa("classify.js");

Store.panelSettings = { custom_lists: [{ id: "cl_mix", name: "cl_mix", domains: ["example.com"], cidrs: ["198.51.100.0/24"] },
                                       { id: "cl_host", name: "cl_host", domains: ["example.org"] }] };
Store.nodes = [{ id: "nk", routing_mode: "sni_kernel" }, { id: "nh", routing_mode: "sni" }, { id: "nf", routing_mode: "forcedns" }];
Store.stats = { nk: { smartroute: { src: 2 } } };

const tgt = raw => ({ t: "target", raw, ...classify(raw) });
const row = (action, b, who) => ({ enabled: true, action, badges: [b], ...(who ? { who } : {}) });
const blkSite = row("block", tgt("ip.me")), dirSite = row("direct", tgt("ifconfig.me"));
const exitSite = row("exit", tgt("ifconfig.me")), blkNet = row("block", tgt("203.0.113.0/24"));
const blkMix = row("block", { t: "list", id: "cl_mix" }), dirHost = row("direct", { t: "list", id: "cl_host" });
const g = (r, mode) => rowGate(r, mode, "nk", r.badges[0]);

console.log("\n[Kernel SNI: Direct and Block by site name run]");
check("Block by site name runs, with no note", g(blkSite, "sni_kernel").ok && !g(blkSite, "sni_kernel").note, g(blkSite, "sni_kernel"));
check("Direct by site name runs", g(dirSite, "sni_kernel").ok && !g(dirSite, "sni_kernel").note, g(dirSite, "sni_kernel"));
check("a list with sites AND networks on a Block row runs whole (no 'IP half alone' note)", g(blkMix, "sni_kernel").ok && !g(blkMix, "sni_kernel").note,
      g(blkMix, "sni_kernel"));
check("a sites-only list on a Direct row runs", g(dirHost, "sni_kernel").ok, g(dirHost, "sni_kernel"));
check("a site is matched as a name here, not 'as text' (PATTERN_ENGINE_OK)", PATTERN_ENGINE_OK.site.sni_kernel === 1, PATTERN_ENGINE_OK.site);

console.log("\n[what the kernel may still be unable to do: bind a per-person row]");
Store.stats = { nk: { smartroute: { src: 1 } } };
const perBlk = row("block", tgt("ip.me"), "w1");
check("a per-person Block by site name on a node that cannot bind devices is inert, with the switch to Hybrid SNI",
      !g(perBlk, "sni_kernel").ok && g(perBlk, "sni_kernel").why === "person_ksni" && g(perBlk, "sni_kernel").fix === "sni", g(perBlk, "sni_kernel"));
Store.stats = { nk: { smartroute: { src: 2 } } };
check("…and runs where it can", g(perBlk, "sni_kernel").ok, g(perBlk, "sni_kernel"));

console.log("\n[unchanged]");
check("Block by network on Kernel SNI runs", g(blkNet, "sni_kernel").ok, g(blkNet, "sni_kernel"));
check("an Exit row by site name on Kernel SNI runs", g(exitSite, "sni_kernel").ok, g(exitSite, "sni_kernel"));
for (const m of ["sni", "forcedns"])
  check("Block and Direct by site name run on " + m, g(blkSite, m).ok && g(dirSite, m).ok, [g(blkSite, m), g(dirSite, m)]);

console.log("\n[the collapsed count and the card agree with it]");
const sum = rulesSummary("nk", [blkSite, dirSite, exitSite, blkNet, blkMix, dirHost], null);
const txt = typeof sum === "string" ? sum : JSON.stringify(sum);
check("the Kernel-SNI summary counts nothing as unable to run", !/can.t run here/.test(txt), txt);
const card = JSON.stringify(MODE_META.sni_kernel);
check("the Kernel SNI card no longer says a site name picks an exit only", !/exit only|Substring match only|content filters inert/.test(card), card.slice(0, 300));
done(PERTURB, "the pre-1.8.8 verdict branch put back");
