/* Self-test: WHICH ADDRESS a NIC exit leaves as — offered where it can be known, reported where it is set.
 *
 * "Leave by eth1" is only half the question on a box with two uplinks; the other half is which of that
 * card's addresses the traffic wears. The panel had that pairing already — and on the WRONG control:
 *
 *   the NAT pin (routes nothing)  the egress-IP list was FILTERED to the pinned card
 *   a NIC exit   (routes)         no source control on the interface sheet at all, and a free-text box on
 *                                 the exit record
 *
 * `_validate_exits` deliberately does not check an exit's `egress_ip` against the node's own addresses, and
 * that reasoning is right for the case it was written for — an adopted TUN belongs to software the panel
 * cannot see. A NETWORK CARD is the other case: the node reports its addresses, so the panel can offer
 * them, and a free-text box where a list would do is how an operator types the OTHER card's address.
 *
 * ⚠️ AND IT IS REPORTED, NOT EDITED, ON THE INTERFACE SHEET. `egress_ip` belongs to the exit, and several
 * interfaces may share one exit — a field here would silently change where other interfaces leave from.
 * [3] pins that the interface sheet only ever tells you, and says where the editing lives.
 *
 * Run: node tests/spa_exitsource_selftest.mjs
 *      --perturb  drops the card's addresses from the picker (the free-text-only shape it shipped as) and
 *                 expects RED.
 */
import { spa, check, done } from "./spa_env.mjs";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(new URL(".", import.meta.url).pathname, "..");

const PERTURB = process.argv.includes("--perturb");
const { cardAddrs, cardGateway, isCardName, EgressPicker } = await spa("routing.js");
const { exitEgressState } = await spa("ui.js");
const { Store } = await spa("store.js");

const NODE = {
  id: "n1", name: "n1", wan_iface: "eth0", ether_ifaces: ["eth0", "eth1"],
  // eth1 carries TWO addresses — the case the whole control exists for
  ether_gws: { eth0: "", eth1: "10.9.0.1" },
  ip_ifaces: [{ ip: "203.0.113.9", iface: "eth0" },
              { ip: "10.9.0.2", iface: "eth1" }, { ip: "10.9.0.3", iface: "eth1" }],
  exits: [{ id: "x1", producer: "adopted", device: "eth1", label: "Second uplink", enabled: true,
            egress_ip: "10.9.0.3" },
          { id: "x2", producer: "adopted", device: "eth1", label: "No source", enabled: true, egress_ip: "" },
          { id: "x3", producer: "imported", provider: "warp", device: "wgx-x3", enabled: true,
            live: { up: true, address: "172.16.0.2" } }],
  exit_candidates: [{ name: "eth1", proto: "nic", offerable: true, gw: "10.9.0.1" }],
};
Store.nodes = [NODE];

console.log("\n[1] the panel knows which addresses sit on which card");
check("a card's own addresses, both of them", JSON.stringify(cardAddrs(NODE, "eth1")) === '["10.9.0.2","10.9.0.3"]',
      JSON.stringify(cardAddrs(NODE, "eth1")));
check("…and not the other card's", !cardAddrs(NODE, "eth1").includes("203.0.113.9"));
check("a device the node reports no addresses for gets an empty list — free text is all there is",
      JSON.stringify(cardAddrs(NODE, "tun0")) === "[]");
check("a missing node answers empty rather than throwing", JSON.stringify(cardAddrs(null, "eth1")) === "[]");

console.log("\n[2] the exit's source picker OFFERS them");
// ⚠️ THE PURE HALF. `ExitEgressPick` uses three hooks, so it cannot be called outside a render and this
// harness has no DOM (tests/spa_env.mjs). `exitEgressState` is the part worth gating — which rows exist and
// which one a stored value lands on — and the component is a thin wrapper over it.
const st = (value, custom) => exitEgressState(value.discovered, PERTURB ? [] : value.addrs, value.value, custom);
const ADDRS = cardAddrs(NODE, "eth1");
const o1 = st({ discovered: "10.9.0.2", value: "", addrs: ADDRS }).options.map(o => String(o.value));
check("both of the card's addresses are rows", o1.includes("10.9.0.2") && o1.includes("10.9.0.3"), o1.join(", "));
check("…beside Auto and a way to type something else",
      o1.includes("") && o1.includes("__custom__"), o1.join(", "));
check("…and Auto names the address the node discovered, when there is one",
      /10\.9\.0\.2/.test(String(st({ discovered: "10.9.0.2", value: "", addrs: ADDRS }).options[0].label)),
      String(st({ discovered: "10.9.0.2", value: "", addrs: ADDRS }).options[0].label));
// ⚠️ A STORED ADDRESS THAT IS ONE OF THE CARD'S MUST SELECT ITS ROW, not open the free-text box under the
// operator — otherwise a value the panel itself offered comes back looking hand-typed.
check("⚠️ a stored address the card has selects that row",
      st({ discovered: "", value: "10.9.0.3", addrs: ADDRS }).sel === "10.9.0.3",
      st({ discovered: "", value: "10.9.0.3", addrs: ADDRS }).sel);
check("…while an address it does NOT have still opens the custom box",
      st({ discovered: "", value: "198.51.100.7", addrs: ADDRS }).sel === "__custom__",
      st({ discovered: "", value: "198.51.100.7", addrs: ADDRS }).sel);
check("…and a blank is Auto", st({ discovered: "", value: "", addrs: ADDRS }).sel === "");
check("an adopted tunnel, whose addresses the panel cannot see, gets Auto + custom only",
      st({ discovered: "10.66.0.2", value: "", addrs: [] }).options.length === 2,
      JSON.stringify(st({ discovered: "10.66.0.2", value: "", addrs: [] }).options.map(o => o.value)));

console.log("\n[3] the interface sheet REPORTS the source, and never edits it");
const hints = value => {
  const out = [];
  const walk = (n, cls) => {
    if (n == null || typeof n !== "object") { if (n != null && cls) out.push([cls, String(n)]); return; }
    if (Array.isArray(n)) return n.forEach(x => walk(x, cls));
    const p = n.props || {};
    walk(p.children, typeof p.class === "string" ? p.class : cls);
  };
  walk(EgressPicker({ node: "n1", value, onChange() {}, noRules: true }), "");
  return out.filter(([c]) => c && c.includes("hint")).map(([, t]) => t).join(" ");
};
const withSrc = hints({ mode: "exit", exitId: "x1" });
check("an exit with a pinned source says which", /10\.9\.0\.3/.test(withSrc), withSrc.slice(0, 200));
check("…and says the source belongs to the exit, not to this interface",
      /belongs to the exit|shares|Settings/.test(withSrc), withSrc.slice(0, 200));
const noSrc = hints({ mode: "exit", exitId: "x2" });
check("an exit with no pinned source says the node picks, and where to pin one",
      /whichever address/.test(noSrc) && /eth1/.test(noSrc), noSrc.slice(0, 200));
check("⚠️ an IMPORTED exit says nothing — its address is not the operator's to set",
      !/Leaves as/.test(hints({ mode: "exit", exitId: "x3" })), hints({ mode: "exit", exitId: "x3" }).slice(0, 160));
check("…and nothing is said when no exit is chosen", !/Leaves as/.test(hints({ mode: "auto" })));
// The interface sheet must not grow a control for it — that is the whole point of [3].
const ddCount = (() => {
  let n = 0;
  const walk = x => {
    if (x == null || typeof x !== "object") return;
    if (Array.isArray(x)) return x.forEach(walk);
    const p = x.props || {};
    if (Array.isArray(p.options)) n++;
    walk(p.children);
  };
  walk(EgressPicker({ node: "n1", value: { mode: "exit", exitId: "x1" }, onChange() {}, noRules: true }));
  return n;
})();
check("the interface sheet offers ONE control in exit mode — the exit itself", ddCount === 1, ddCount + " dropdowns");

console.log("\n[4] ⚠️ EVERY render site hands it the addresses");
// I threaded `addrs` through the two ExitFields callers and shipped it — and the exits GRID renders
// `ExitEgressPick` DIRECTLY, so the column an operator actually uses still offered "Auto | custom…" and
// nothing else. Caught in a browser, not by [2], because [2] tests the function and this is about the call
// sites. Same shape as every "N places name it" defect in this tree: read them from source and count.
{
  const src = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
  const sites = [...src.matchAll(/<\$\{ExitEgressPick\}([\s\S]{0,300}?)\/>/g)].map(m => m[1]);
  check("the settings screen renders it in more than one place", sites.length >= 3, sites.length + " sites");
  const bare = sites.filter(a => !/addrs=/.test(a));
  check("⚠️ …and every one of them passes `addrs`", !bare.length,
        bare.length + " site(s) without it: " + bare.map(a => a.slice(0, 60).replace(/\s+/g, " ")).join(" || "));
  // …and the component that wraps it must pass its own prop through, or the two ExitFields callers are moot
  check("ExitFields forwards the prop it was given", /addrs=\$\{addrs\}/.test(src));
}

console.log("\n[5] ⚠️ the TYPED GATEWAY is reachable — decision 2 shipped a field, not just a column");
// Found in review: `gw` was validated, stored, threaded to the node, given a residue rule and put in the
// SPA's field whitelist — and there was no box to type it in. The refusal sentence for a gatewayless card
// says "set the gateway on the exit under Settings → Network", so the UI was promising a control that did
// not exist, for exactly the boxes the rig proved detection cannot serve.
check("a card is recognised as one", isCardName(NODE, "eth1") === true);
check("…and a tunnel is not, so the field is not offered where the node ignores it",
      isCardName(NODE, "tun0") === false && isCardName(NODE, "wgx-x3") === false);
check("the detected gateway is readable for the placeholder", cardGateway(NODE, "eth1") === "10.9.0.1",
      cardGateway(NODE, "eth1"));
check("…and a card with none reads empty, not undefined", cardGateway(NODE, "eth0") === "");
check("a node that never reported gateways reads empty rather than throwing",
      cardGateway({ id: "n1" }, "eth1") === "");
{
  const src = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
  check("⚠️ the exit form renders a Gateway field", /exname-gw/.test(src) && /onChange\(\{ gw:/.test(src));
  check("…only for a card", /\$\{isNic \? fld\("exname-gw"/.test(src));
  // ⚠️ COUNTED, NOT WINDOWED. A fixed look-ahead missed both call sites: they carry embedded `${/* … */""}`
  // comments and run well past any window worth hard-coding. One `isNic=` and one `gw=` per caller is the
  // property, and it does not care how long the call is.
  const callers = (src.match(/<\$\{ExitFields\}/g) || []).length;
  check("…and every ExitFields caller supplies what it needs",
        callers >= 2 && (src.match(/isNic=/g) || []).length === callers
                     && (src.match(/\bgw=\$\{cardGateway/g) || []).length === callers,
        callers + " callers, " + (src.match(/isNic=/g) || []).length + " isNic, "
                + (src.match(/\bgw=\$\{cardGateway/g) || []).length + " gw");
}

done(PERTURB, "the card's addresses dropped from the picker");
