/* Self-test: pinning a NIC that this node's routing will not use SAYS SO.
 *
 * The defect (NIC-EXIT-PLAN §7), live on `main` and on `dev` and independent of the NIC-exit feature:
 * `Direct — <nic>` is a NAT selector, not a route. `_egress_des` (swg-noded:1629) is a ladder that RETURNS
 * on `wan_ov`, so pinning a card the node's default route does not use produces exactly one MASQUERADE
 * `-o <that card>` which can never match — AND the baseline MASQUERADE out the real WAN is never added
 * either. The clients egress un-NATted, are dropped upstream, and every screen keeps saying the interface
 * is healthy. It is the `Direct — wdttraw2` defect one layer down: there a device that could not carry
 * traffic was offered, here a device that can is pinned for a job it is not doing.
 *
 * ⚠️ WHAT IS BEING GATED IS A WARNING, NOT A REFUSAL. A second uplink the operator policy-routes to by hand
 * outside the panel is a real setup and this control is the only way to NAT for it, so [4] pins down that
 * Save is still allowed. A test that demanded a refusal would lock in the wrong behaviour.
 *
 * Run: node tests/spa_nicpin_selftest.mjs
 *      --perturb  blanks the node's reported `wan_iface`, which is the ONLY input the warning is derived
 *                 from — i.e. the component as it shipped, blind to where the node's traffic leaves — and
 *                 expects the warning checks to go red. It does not perturb the render path; [1] covering
 *                 the real module is what carries that.
 */
import { spa, check, done } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const { EgressPicker, NatSourcePick, natPinApplies, egressBody } = await spa("routing.js");
const { Store } = await spa("store.js");

// A two-NIC node: eth0 carries the default route, eth2 is a second card that routing does not use — the
// exact shape msk-main reports, and the shape a stranger's box with a LAN NIC reports too.
// It carries a healthy exit and a peer node too, so [2] can put the picker in `exit` and `forward` mode
// WITHOUT tripping one of the notes that already lived beside this one — a blank exit id renders "that exit
// no longer exists", which is correct behaviour and would otherwise read here as our warning firing.
const NODE = { id: "n1", name: "n1", wan_iface: "eth0", ether_ifaces: ["eth0", "eth2"],
               exits: [{ id: "x1", producer: "adopted", device: "tun-lab0", label: "Lab", enabled: true }],
               ip_ifaces: [{ ip: "203.0.113.9", iface: "eth0" }, { ip: "192.0.2.2", iface: "eth2" }] };
const PEER = { id: "n2", name: "n2", exits: [], ips: ["198.51.100.7"] };
const NODES = () => [PERTURB ? { ...NODE, wan_iface: "" } : NODE, PEER];
Store.nodes = NODES();

/* The hints the picker actually renders, by class. Walks the vnode tree rather than a DOM — see
   tests/spa_env.mjs for why there is no DOM here and what that costs. `class` is inherited down into
   children so the text nodes under a `<div class="hint err">` are attributed to it. */
function hints(value) {
  const out = [];
  const walk = (n, cls) => {
    if (n == null || typeof n === "boolean") return;
    if (Array.isArray(n)) return n.forEach(x => walk(x, cls));
    if (typeof n === "string" || typeof n === "number") { if (cls) out.push([cls, String(n)]); return; }
    const p = (n && n.props) || {};
    walk(p.children, typeof p.class === "string" ? p.class : cls);
  };
  // ⚠️ THE WARNING MOVED WITH THE CONTROL. It used to be rendered by `EgressPicker`, beside the NIC rows;
  // both are now `NatSourcePick`, which each sheet places under "Advanced settings". Walking the old
  // component would find nothing and every check here would go quietly green.
  walk(NatSourcePick({ node: "n1", value, onChange() {} }), "");
  return out;
}
const warnOf = value => hints(value).filter(([c]) => c === "hint err").map(([, t]) => t).join(" ");

console.log("\n[1] a NIC the node's traffic does not leave by is called out");
const w = warnOf({ mode: "direct", nic: "eth2" });
check("pinning eth2 on a box that leaves by eth0 warns", !!w, JSON.stringify(w));
check("…the sentence names the card that was pinned", w.includes("eth2"), w);
check("…and the card the traffic actually leaves by, so it points somewhere", w.includes("eth0"), w);
check("…and says the consequence, not just that something is off",
      /NAT/.test(w) && /never/.test(w), w);

console.log("\n[1b] …under EITHER spelling of the one mode a pin is live in");
// A pin is stored identically whether the draft says `auto` or `direct` — so both must warn, or the
// warning is missing exactly while the operator is making the mistake.
check("a pin on a draft still spelled `auto` warns too", !!warnOf({ mode: "auto", nic: "eth2" }),
      warnOf({ mode: "auto", nic: "eth2" }));
check("…and says the same thing as the `direct` spelling",
      warnOf({ mode: "auto", nic: "eth2" }) === warnOf({ mode: "direct", nic: "eth2" }));

console.log("\n[2] the cases that must stay silent");
check("pinning the card the node DOES leave by is fine", !warnOf({ mode: "direct", nic: "eth0" }),
      warnOf({ mode: "direct", nic: "eth0" }));
check("direct with no card pinned is fine", !warnOf({ mode: "direct", nic: "" }));
// `nic` is carried across a mode switch by design (see `onIf`), so a stale one must not warn from a mode
// that never reaches `_egress_des`'s `wan_ov` arm at all. Each mode is given the rest of its value so the
// only `hint err` it could produce is ours.
//
// ⚠️ `auto` IS NOT ONE OF THEM, and that changed deliberately when the pin was demoted to its own control.
// `egressBody` stores `auto`+nic and `direct`+nic as exactly the same record, so a pin is LIVE under both
// spellings — and a freshly-pinned draft is still `auto` until it has been saved and read back. Testing
// only `direct` meant the warning was silent for the whole first edit, which is precisely when it is worth
// saying. [1b] asserts the opposite of what this loop used to.
for (const [m, extra] of [["smart", { rows: [] }], ["forward", { node: "n2" }], ["exit", { exitId: "x1" }]]) {
  check(`mode ${m} never warns about a NIC`, !warnOf({ mode: m, nic: "eth2", ...extra }),
        warnOf({ mode: m, nic: "eth2", ...extra }));
}

console.log("\n[3] a node that has not said where it leaves by is not evidence of a mismatch");
// "found nothing" is not "asked and there is nothing" — the same rule the NIC list and the refusal set
// follow. A panel that cried wolf here would fire on every node for the whole window after a restart.
Store.nodes = [{ ...NODE, wan_iface: "" }, PEER];
check("blank wan_iface stays silent", !warnOf({ mode: "direct", nic: "eth2" }),
      warnOf({ mode: "direct", nic: "eth2" }));
Store.nodes = [{ id: "n1", name: "n1", exits: [] }, PEER];
check("a node with no reported fields at all stays silent", !warnOf({ mode: "direct", nic: "eth2" }));
Store.nodes = NODES();

console.log("\n[3b] the egress picker no longer carries it at all");
// The pin is not an egress destination — that is the whole reason it moved. If a copy were left behind,
// two controls would edit one field and only one of them would carry the warning.
{
  const seen = [];
  const walk = n => {
    if (n == null || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(walk);
    const p = n.props || {};
    if (Array.isArray(p.options)) p.options.forEach(o => seen.push(String((o || {}).value || "")));
    walk(p.children);
  };
  Store.nodes = NODES();
  walk(EgressPicker({ node: "n1", value: { mode: "direct", nic: "eth2" }, onChange() {}, noRules: true }));
  check("the egress picker offers no `direct|<nic>` row", !seen.some(v => v.startsWith("direct|")), seen.join(", "));
}

console.log("\n[3c] ⚠️ the pin is not offered in a mode that would THROW IT AWAY — or destroy that mode");
// Found in review, before this shipped. The control set `mode` so its value would mean something, and it
// was rendered in every mode — so an interface on an exit lost its `exit_id`, and one on smart routing lost
// every routing rule, from a dropdown inside a collapsed "Advanced" section. `egressBody` only carries
// `wan_iface` for auto/direct; the other modes never stored it in the first place.
for (const m of ["exit", "smart", "forward"]) {
  check(`mode ${m}: the pin is not offered`,
        NatSourcePick({ node: "n1", value: { mode: m, nic: "" }, onChange() {} }) === null);
  check(`…and \`natPinApplies\` agrees, so the sheets' summaries follow it`, !natPinApplies({ mode: m }));
}
for (const m of ["auto", "direct"]) {
  check(`mode ${m}: the pin IS offered`,
        NatSourcePick({ node: "n1", value: { mode: m, nic: "" }, onChange() {} }) !== null);
  check(`…and applies`, natPinApplies({ mode: m }));
}
// ⚠️ THE CONSEQUENCE, asked of the save path rather than inferred: the modes that hide the control are
// exactly the modes whose saved body has no `wan_iface` to carry.
for (const [m, body] of [["exit", { mode: "exit", exitId: "x1", nic: "eth2" }],
                         ["smart", { mode: "smart", rows: [], nic: "eth2" }]]) {
  check(`a ${m} save carries no wan_iface, so a pin there would be discarded`,
        !("wan_iface" in egressBody(body)), JSON.stringify(egressBody(body)));
}
check("…while a direct save does carry it", egressBody({ mode: "direct", nic: "eth2" }).wan_iface === "eth2");

console.log("\n[4] it warns, it does not refuse");
const { egressSaveBlock } = await spa("routing.js");
check("a pinned mismatched NIC still saves", !egressSaveBlock({ mode: "direct", nic: "eth2", rows: [] }, "kernel"),
      String(egressSaveBlock({ mode: "direct", nic: "eth2", rows: [] }, "kernel")));

done(PERTURB, "node blind to its own WAN, the way it shipped");
