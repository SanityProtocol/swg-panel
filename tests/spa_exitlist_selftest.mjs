/* Self-test: every picker offers the SAME ways out, and an exit is spelled the same way in all of them.
 *
 * Four controls ask "where does this leave by" — the node's default exit, an interface's egress, a smart
 * rule's destination and the catch-all. They are four callers of ONE builder, `exitOptionGroups`, and they
 * had drifted: the node's picker offered the devices the node reports and the other three did not, so an
 * operator could send the whole node out `wg-lab0` but not a single interface. The same device was present
 * in one list and absent from the one below it.
 *
 * The labels had drifted the same way — a bare `wgx-229f0c44` in one place, `Custom — <title> — <device>`
 * in another, and a discovered device rendering as a naked interface name that said nothing about what it
 * was. `exitLabel` is the one namer now.
 *
 * ⚠️ THIS IS THE FIRST TEST OF ANY SPA LOGIC IN THIS TREE. Everything in js/ had been verified by driving a
 * browser, which proves a behaviour once and prevents nothing. See tests/spa_env.mjs for what the harness
 * is and — more importantly — what it deliberately is not.
 *
 * Run: node tests/spa_exitlist_selftest.mjs      --perturb  drops `devices` from the interface picker, the
 * way it shipped, and expects the lists to disagree.
 */
import { spa, check, done, FAILS } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const { exitOptionGroups, exitLabel, exitTypeLabel, exitHealth, exitHealthMark } = await spa("routing.js");

// A node with one of every kind the panel can produce.
const NODE = {
  id: "n1", name: "n1",
  exits: [
    { id: "a1", producer: "imported", provider: "warp", device: "wgx-a1", label: "TW", enabled: true },
    { id: "a2", producer: "imported", provider: "warp", device: "wgx-a2", label: "", enabled: true },
    { id: "a3", producer: "imported", provider: "warp", device: "wgx-a3", label: "", licence: "K-K-K", enabled: true },
    { id: "a4", producer: "imported", provider: "profile", device: "wgx-a4", label: "", enabled: true },
    { id: "b1", producer: "adopted", device: "tun-lab0", label: "Lab", enabled: true },
    { id: "b2", producer: "adopted", device: "tun-hand", label: "", enabled: true },
    // the stored label that merely repeats the device — `_validate_exits` writes plenty of these
    { id: "b3", producer: "adopted", device: "tun-echo", label: "tun-echo", enabled: true },
  ],
  exit_candidates: [{ name: "tun-lab0", offerable: true }, { name: "wg-found", offerable: true },
                    { name: "eth0", offerable: false, why_not: "nic" }],
};
// each exit carries live state where the health model wants it
NODE.exits.forEach(x => { if (x.producer === "imported") x.live = { up: true, address: "172.16.0.2" }; });

console.log("\n[1] one name for an exit, in every list");
const L = id => exitLabel(NODE.exits.find(x => x.id === id), NODE);
check("a titled WARP account keeps its title, and still shows its device", L("a1") === "TW — wgx-a1", L("a1"));
check("an untitled WARP account says what it IS", L("a2") === "WARP exit — wgx-a2", L("a2"));
check("…and a licensed one says WARP+", L("a3") === "WARP+ exit — wgx-a3", L("a3"));
check("a pasted profile is a Custom exit", L("a4") === "Custom exit — wgx-a4", L("a4"));
check("an adopted device the node REPORTS is Discovered", L("b1") === "Lab — tun-lab0", L("b1"));
check("…and an untitled reported one says so", exitLabel({ producer: "adopted", device: "tun-lab0" }, NODE)
      === "Discovered — tun-lab0", exitLabel({ producer: "adopted", device: "tun-lab0" }, NODE));
check("a device the node does NOT report is Custom", L("b2") === "Custom — tun-hand", L("b2"));
// `tun-echo` is NOT one of the node's reported candidates, so its KIND is Custom — the point of the check
// is that the stored title ("tun-echo") was dropped for being the device name again, not which kind it is.
check("⚠️ a label that merely repeats the device is not a title", L("b3") === "Custom — tun-echo", L("b3"));
check("no device, no dash", exitTypeLabel({ producer: "imported", provider: "warp" }, NODE) === "WARP exit"
      && exitLabel({ producer: "imported", provider: "warp" }, NODE) === "WARP exit");

console.log("\n[2] the four pickers offer the SAME ways out");
// how each control calls the shared builder — the node's own picker also carries row controls and a
// "Custom interface…" sentinel, which are about MANAGING exits, not about which exits exist.
const opts = {
  "node default":   { prefix: "", devices: true, custom: "__custom__" },
  "interface egress": { prefix: "exit|", devices: true },
  "rule destination": { prefix: "dev|", devices: true },
  "catch-all":        { prefix: "dev|", devices: true },
};
if (PERTURB) opts["interface egress"] = { prefix: "exit|" };   // how it shipped: no devices here

const setOf = o => new Set(exitOptionGroups(NODE, o)
  .flatMap(g => g.items || [g])
  .map(i => String(i.value).replace(/^(exit\||dev\|)/, ""))
  .filter(v => v !== "__custom__"));
const sets = Object.fromEntries(Object.entries(opts).map(([k, o]) => [k, setOf(o)]));
const base = sets["node default"];
for (const [name, s] of Object.entries(sets)) {
  if (name === "node default") continue;
  const missing = [...base].filter(v => !s.has(v)), extra = [...s].filter(v => !base.has(v));
  check(`${name} offers exactly what the node's own picker does`, !missing.length && !extra.length,
        "missing: " + JSON.stringify(missing) + " extra: " + JSON.stringify(extra));
}
check("…and that set includes the reported device nobody has a record for yet",
      base.has("dev:wg-found"), [...base].join(", "));
check("a device the panel REFUSES is offered by none of them",
      ![...base].some(v => v.includes("eth0")), [...base].join(", "));

console.log("\n[3] the same exit reads the same way whichever list it is in");
const labelsIn = o => Object.fromEntries(exitOptionGroups(NODE, o).flatMap(g => g.items || [g])
  .map(i => [String(i.value).replace(/^(exit\||dev\|)/, ""), i.label]));
const ref = labelsIn(opts["node default"]);
for (const name of ["rule destination", "catch-all"]) {
  const here = labelsIn(opts[name]);
  const differ = Object.keys(ref).filter(k => here[k] !== undefined && here[k] !== ref[k]);
  check(`${name} spells every exit the way the node's picker does`, !differ.length,
        differ.map(k => `${k}: ${ref[k]} vs ${here[k]}`).join(" · "));
}

console.log("\n[4] a row that cannot be chosen is listed, dimmed, and says why");
const off = { ...NODE, exits: [...NODE.exits, { id: "z1", producer: "adopted", device: "tun-off", label: "Off", enabled: false }] };
const row = exitOptionGroups(off, { prefix: "" }).flatMap(g => g.items || [g]).find(i => i.value === "z1");
check("a switched-off exit is still in the list", !!row);
check("…dimmed rather than removed from keyboard reach", row && row.className === "dim" && !row.disabled, row && row.className);
check("…and refuses with a reason", row && typeof row.refuse === "string" && row.refuse.length > 0, row && row.refuse);

console.log("\n[6] PROGRESS IS NOT A FAULT — a state that is not a warning must not look like one");
// A WARP account the node has not finished registering wore the SAME amber warning triangle as a failed
// one, so the first thing an operator saw after creating an exit was the panel calling it broken. Found in
// the browser, 1.8.5 qualification.
const _mk = x => ({ id: "z1", producer: "imported", provider: "warp", device: "wgx-z1", label: "", enabled: true, ...x });
const H = {
  creating: exitHealth(_mk({ live: {} }), NODE),                                   // node has not made it yet
  failed:   exitHealth(_mk({ live: { error: "registration refused" } }), NODE),
  down:     exitHealth(_mk({ live: { device: "wgx-z1", up: false } }), NODE),
  ok:       exitHealth(_mk({ live: { device: "wgx-z1", up: true } }), NODE),
};
check("a WARP account still being created is NOT toned as a warning",
      H.creating.tone !== "warn" && H.creating.tone !== "bad", H.creating.tone);
check("…it is `busy`, and it names an in-progress icon",
      H.creating.tone === "busy" && H.creating.icon === "refresh",
      H.creating.tone + "/" + H.creating.icon);
check("…and it does NOT borrow the warning icon", (H.creating.icon || "warn") !== "warn", H.creating.icon);
check("a FAILED exit is still a fault", H.failed.tone === "bad", H.failed.tone);
check("a DOWN exit is still a warning", H.down.tone === "warn", H.down.tone);
check("a healthy exit carries no marker at all", !H.ok.tone, H.ok.tone);
// ⚠️ ONE renderer. Three screens drew this by hand and all three hardcoded the triangle, which is why a
// non-warning state had no way to look different. The marker must honour whatever icon the verdict names.
const drawn = t => JSON.stringify(exitHealthMark(t));
check("the shared marker renders the icon the verdict asked for",
      drawn(H.creating).includes("refresh"), drawn(H.creating));
check("…and still renders `warn` for the states that mean it",
      drawn(H.down).includes("warn"), drawn(H.down));
check("…and draws nothing when there is nothing to say", exitHealthMark(H.ok) === null);

// ── the two controls the grid does not explain anywhere else ──────────────────────────────────────────
// ⚠️ SOURCE, NOT RENDER, and knowingly so: what is being asserted is that a `title` is PASSED, which is the
// half that was missing. Whether the browser draws it is a browser question and was checked there. Kill-switch
// and Active are deliberately absent from the editor sheet ("one click in the grid"), so the grid's hover is
// the ONLY place either is explained — and both shipped with none, while the latency cell beside them carried
// two sentences. Two grids render the pair; both are checked, because one is how they drift apart.
import fs from "node:fs";
import path from "node:path";
const SS = fs.readFileSync(path.join(process.env.SPA_ROOT, "js", "screen-settings.js"), "utf8");
// ⚠️ SLICE THE WHOLE ELEMENT, don't regex to the first keyword. The first version stopped the match at
// `killswitch` — which in one of the two sites appears BEFORE the title — so it reported a missing title on
// code that had one. A verifier that reads part of the thing it judges is a verifier that reports on
// something else.
const switches = SS.split("<${Switch}").slice(1).map(c => c.slice(0, c.indexOf("/>") + 2));
const swKS = switches.filter(c => /killswitch/.test(c));
const swAC = switches.filter(c => /on=\$\{!off\}/.test(c));
check("both exits grids render a kill-switch", swKS.length === 2, swKS.length);
check("…and each one says what it does", swKS.every(c => /title=\$\{KS_TITLE\(\)\}/.test(c)),
      swKS.map(c => c.replace(/\s+/g, " ").slice(0, 100)));
check("both exits grids render an Active switch", swAC.length === 2, swAC.length);
check("…and each one says that pausing KEEPS the account",
      swAC.every(c => /title=\$\{ACTIVE_TITLE\(\)\}/.test(c)),
      swAC.map(c => c.replace(/\s+/g, " ").slice(0, 100)));
// ⚠️ ONE wording, not two — the sentences live in one place precisely so the two grids cannot disagree.
check("…and the wording is declared once, not copied per grid",
      (SS.match(/const KS_TITLE = /g) || []).length === 1
      && (SS.match(/const ACTIVE_TITLE = /g) || []).length === 1);
check("the Active sentence is the one an operator needs: the account survives",
      /account and keys are kept/.test(SS));
check("the kill-switch sentence names BOTH states, not just the on one",
      /traffic using it is refused\. Off: it falls back/.test(SS));

done(PERTURB, "interface picker without `devices`");
