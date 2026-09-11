/* Self-test: opening an interface editor must pick the sheet that matches the interface's KIND.
 *
 * Three kinds, three sheets. A csqtt or WDTT server owns its own tunnel and its settings live under the
 * node's `csqtt`/`wdtt` map, not under `ifaces` — so the WireGuard sheet opened on one finds nothing it
 * recognises: no tunnel IP (it renders "—"), an empty external port, and an egress mode of
 * "Auto (MASQUERADE)" for a server stored as `smart` WITH rules. Nothing is wrong on the node; the editor is
 * reading the wrong half of the record, and Save would write that emptiness back over a working config.
 *
 * Reported from the Routing-lists screen, whose interface chips open "the interface that asked for this
 * list" and cannot know which kind it is — it called `openEditIface` unconditionally for all three.
 *
 * ⚠️ THE TWO SHEETS ARE NOT TELLABLE APART BY TITLE. `EditWdttSheet` renders "Edit WDTT interface · x" and
 * the generic one renders "Edit {KIND} interface · x", which for a WDTT interface is the same sentence in
 * both languages. A test that read the heading would have passed on the bug. So this asserts the DISPATCH:
 * the caller routes through a function that asks the kind, and that function names all three sheets.
 *
 * Run: node tests/spa_ifaceeditor_dispatch_selftest.mjs     --perturb  restores the unconditional call.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
let IF = readFileSync(path.join(ROOT, "js", "iface.js"), "utf8");
let SET = readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");

const ANCH = "onClick=${() => openIfaceEditor(selNode, ifn)}";
check("anchor present — else this run would FALSE-PASS", SET.includes(ANCH));
if (PERTURB) SET = SET.replace(ANCH, "onClick=${() => openEditIface(selNode, ifn)}");

/* ── the dispatcher exists and knows all three kinds ── */
const i = IF.indexOf("export function openIfaceEditor");
check("a kind-dispatching opener exists", i > 0);
const fn = i > 0 ? IF.slice(i, IF.indexOf("\n}", i)) : "";
check("it asks the kind", /iTypeOf\(node, iface\)/.test(fn), fn.slice(0, 200));
for (const [kind, opener] of [["csqtt", "openEditCsqtt"], ["wdtt", "openEditWdtt"]])
  check(`${kind} routes to ${opener}`, new RegExp(`"${kind}"[\\s\\S]{0,60}${opener}\\(node, iface\\)`).test(fn), fn);
check("anything else falls back to the WireGuard sheet", /return openEditIface\(node, iface\);/.test(fn), fn);

/* ── and the caller that could not know the kind uses it ── */
check("the Routing-lists interface chip dispatches by kind", SET.includes("openIfaceEditor(selNode, ifn)"));
check("…and no longer calls the WireGuard sheet directly", !SET.includes("openEditIface(selNode, ifn)"));

/* ── the two callers that DO know their kind are left alone (this is not a blanket rewrite) ── */
check("the WG interface detail still opens the WG sheet", IF.includes("openEditIface(node, iface)"));
check("WdttIfaceDetail still picks between the two self-contained sheets",
      /isCsq \? openEditCsqtt\(node, iface\) : openEditWdtt\(node, iface\)/.test(IF));

/* ── the reason a title check would not have caught this ── */
const ru = readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
check("the WDTT sheet and the generic sheet render the same heading for a WDTT interface",
      ru.includes('"Edit WDTT interface · {v1}": "Правка интерфейса WDTT · {v1}"')
      && ru.includes('"Edit {v1} interface · {v2}": "Правка интерфейса {v1} · {v2}"'));

done();
