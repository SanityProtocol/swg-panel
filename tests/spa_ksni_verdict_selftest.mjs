/* Self-test: on KERNEL SNI a Direct or Block rule matches by ADDRESS only, and its row says so.
 *
 * The in-kernel scanner learns a site's address only for a rule that leaves by an exit — swg-noded hands
 * `_ensure_smart_xtstring` its exit rows alone, and nothing else lowers a Direct or Block row's names. Measured on
 * msk-main from a wiped table (1.8.8 qualification): `ip.me → Block` let the site through, and `ifconfig.me →
 * Direct` above a catch-all forward went out the forward anyway — while the rule list showed both as working
 * (`PATTERN_ENGINE_OK.site.sni_kernel` is "text" whatever the row's action). The row gate now tells the truth: a
 * site badge on a Direct or Block row is inert on Kernel SNI with the switch to Hybrid SNI, a list holding both kinds
 * keeps its IP half and says so, and nothing changes for an exit row or for any other engine.
 *
 * Run: node tests/spa_ksni_verdict_selftest.mjs
 *      --perturb   takes the verdict branch out of `rowGate` (the shipped behaviour) and expects red.
 */
import { spa, check, done, ROOT } from "./spa_env.mjs";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PERTURB = process.argv.includes("--perturb");
let R;
if (PERTURB) {
  const src = fs.readFileSync(path.join(ROOT, "js", "routing.js"), "utf8");
  const a = '  if (row && (row.action === "direct" || row.action === "block"))\n';
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING: the verdict branch"); process.exit(1); }
  const tmp = path.join(ROOT, "js", "__perturb_ksni_verdict.js");
  fs.writeFileSync(tmp, src.replace(a, "  if (false)\n"));
  try { R = await import(pathToFileURL(tmp).href); } finally { fs.unlinkSync(tmp); }
} else {
  R = await spa("routing.js");
}
const { rowGate, gateReason, rulesSummary } = R;
const { Store } = await spa("store.js");
const { classify } = await spa("classify.js");

// a custom list holding a site AND a network, so its capability is known here without a catalog
Store.panelSettings = { custom_lists: [{ id: "cl_mix", name: "cl_mix", domains: ["example.com"], cidrs: ["198.51.100.0/24"] },
                                       { id: "cl_host", name: "cl_host", domains: ["example.org"] }] };
Store.nodes = [{ id: "nk", routing_mode: "sni_kernel" }, { id: "nh", routing_mode: "sni" }, { id: "nf", routing_mode: "forcedns" }];
Store.stats = { nk: { smartroute: { src: 2 } } };

// rows as the editor holds them (one badge each, so each check reads exactly one verdict)
const tgt = raw => ({ t: "target", raw, ...classify(raw) });
const row = (action, b) => ({ enabled: true, action, badges: [b] });
const blkSite = row("block", tgt("ip.me")), dirSite = row("direct", tgt("ifconfig.me"));
const exitSite = row("exit", tgt("ifconfig.me")), devSite = row("dev", tgt("ifconfig.me"));
const blkNet = row("block", tgt("203.0.113.0/24"));
const blkMix = row("block", { t: "list", id: "cl_mix" }), dirHost = row("direct", { t: "list", id: "cl_host" });
const rows = [blkSite, dirSite, exitSite, devSite, blkNet, blkMix, dirHost];
const g = (row, mode) => rowGate(row, mode, "nk", row.badges[0]);

console.log("\n[Kernel SNI: a Direct or Block row matches by address only]");
check("Block by site name → inert, with the switch to Hybrid SNI", !g(blkSite, "sni_kernel").ok && g(blkSite, "sni_kernel").why === "ksni_verdict"
      && g(blkSite, "sni_kernel").fix === "sni", g(blkSite, "sni_kernel"));
check("Direct by site name → inert, the same verdict", !g(dirSite, "sni_kernel").ok && g(dirSite, "sni_kernel").why === "ksni_verdict", g(dirSite, "sni_kernel"));
check("a list with sites AND networks on a Block row → its IP half runs, and the note says so",
      g(blkMix, "sni_kernel").ok && /IP addresses and networks alone/.test(g(blkMix, "sni_kernel").note || ""), g(blkMix, "sni_kernel"));
check("a sites-only list on a Direct row → inert", !g(dirHost, "sni_kernel").ok && g(dirHost, "sni_kernel").why === "ksni_verdict", g(dirHost, "sni_kernel"));
check("the reason is one sentence that names the fix", /Direct or Block rule by site name does nothing here/.test(gateReason(g(blkSite, "sni_kernel"), "Kernel SNI")));

console.log("\n[unchanged: what the node does lower, and every other engine]");
check("Block by network on Kernel SNI still runs", g(blkNet, "sni_kernel").ok, g(blkNet, "sni_kernel"));
check("an Exit row by site name on Kernel SNI still runs", g(exitSite, "sni_kernel").ok, g(exitSite, "sni_kernel"));
check("a device-exit row by site name on Kernel SNI still runs", g(devSite, "sni_kernel").ok, g(devSite, "sni_kernel"));
for (const m of ["sni", "forcedns"])
  check("Block and Direct by site name run on " + m, g(blkSite, m).ok && g(dirSite, m).ok, [g(blkSite, m), g(dirSite, m)]);

console.log("\n[the collapsed section's count says it]");
const sum = rulesSummary("nk", rows, null);
const txt = typeof sum === "string" ? sum : JSON.stringify(sum);
check("the Kernel-SNI summary counts the two site badges and the sites-only list as unable to run", /3/.test(txt) && /can.t run here/.test(txt), txt);
done(PERTURB, "the verdict branch removed");
