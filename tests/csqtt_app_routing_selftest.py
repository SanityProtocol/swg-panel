#!/usr/bin/env python3
"""Self-test: csqtt 2.5 App routing, the panel's and the node's halves (docs/CSQTT-APP-ROUTING-PLAN.md).

One routing rule per server, which the 2.5 server hands each user's app on connect: apps / domains / addresses that go
direct (bypass the tunnel), or the reverse ("only these use the tunnel"). The panel stores what the app itself keeps
(rust-client sni.rs parse_direct_domains / parse_ip_rules) and refuses what it would drop.

  [1] panel _validate_app_routing: lists from text or arrays, deduped, domains lower-cased with "*."/"." stripped; every
      refusal (a bad app ID / domain / address, a cap); "only these" with an EMPTY list is refused for apps, domains and
      addresses (it would send nothing through the tunnel); the built-in list only in direct mode; all-defaults = no rule
  [2] delivery: csqtt_cfg (the SPA's) publishes app_routing, the node's reply carries it as stored
  [3] node desired.json: byte-identical without a rule (no rewrite, no SIGHUP on an update); carries the server's rule,
      its known keys only; a rule of the wrong shape is dropped whole (the server would reject the file)
  [4] node drift: a rule added, changed or removed is a change; the same rule is not

Hermetic. Run: python3 tests/csqtt_app_routing_selftest.py   (0 = pass)
     --perturb-empty    an "only these" mode with an empty list is stored → RED in [1]
     --perturb-always   desired.json always carries app_routing → RED in [3]
     --perturb-norm     addresses stored as typed → RED in [1]
     --perturb-idna2003 the whole-name IDNA 2003 codec instead of punycode label by label → RED in [1]
"""
import json, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

P_PLANTS = {"--perturb-norm": ("""                ips.append(str(n) if n.prefixlen < 32 else str(n.network_address))""",
                               """                ips.append(x)"""),
            "--perturb-idna2003": ("""        a = _ar_wire_name(h) if len(h) <= 253 else \"\"""",
                                   """        a = h if h.isascii() else h.encode("idna").decode("ascii")"""),
            "--perturb-empty": ('''    if apps == "only" and not pk:
        return None, perr("App routing: list at least one app to send through the tunnel")''', '''    if False:
        pass''')}
N_PLANTS = {"--perturb-always": ('''    ar = _csqtt_app_routing(inst.get("app_routing"))
    if ar:
        body["app_routing"] = ar''', '''    body["app_routing"] = _csqtt_app_routing(inst.get("app_routing"))''')}
MODE = next((a for a in sys.argv[1:] if a in P_PLANTS or a in N_PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(path, name, plants):
    src = open(path, encoding="utf-8").read()
    if MODE in plants:
        cut, new = plants[MODE]
        # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
        assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
        src = src.replace(cut, new, 1)
    m = types.ModuleType(name)
    m.__dict__.update({"__name__": name, "__file__": path})
    exec(compile(src.split("\nif __name__ ==")[0], os.path.basename(path), "exec"), m.__dict__)
    return m

P = load(PANEL, "p", P_PLANTS)
N = load(NODED, "n", N_PLANTS)
V = P._validate_app_routing

print("[1] the panel's validation")
rec, err = V({"apps_mode": "except", "packages": "org.telegram.messenger\ncom.x\ncom.x", "domains": "*.YA.ru, .vk.com.",
              "template_domains": True, "ips": ["10.0.0.0/8", "10.9.0.1-10.9.0.9", "192.168.1.10"]})
check("lists from text or arrays, deduped; domains lower-cased, *. / . stripped",
      err is None and rec["packages"] == ["org.telegram.messenger", "com.x"] and rec["domains"] == ["ya.ru", "vk.com"]
      and rec["ips"] == ["10.0.0.0/8", "10.9.0.1-10.9.0.9", "192.168.1.10"] and rec["template_domains"] is True, (rec, err))
for bad, key in (({"apps_mode": "except", "packages": ["telegram"]}, "Android app ID"),
                 ({"domains": ["bad_dom!"]}, "is not a domain"),
                 ({"ips": ["10.0.0.0/33"]}, "IP address or range"),
                 ({"apps_mode": "sometimes"}, "not a valid setting"),
                 ({"domains": ["d%d.ru" % i for i in range(501)]}, "at most")):
    r, e = V(bad)
    check("refused: %s" % key, r is None and e and key in e["error"], (r, e))
for mode, key in (({"apps_mode": "only"}, "app"), ({"domains_mode": "tunnel"}, "domain"), ({"ips_mode": "tunnel"}, "address")):
    r, e = V(mode)
    check("\"only these\" %ss with an empty list is refused (nothing would use the tunnel)" % key,
          r is None and e and "at least one " + key in e["error"], (r, e))
r, e = V({"domains_mode": "tunnel", "domains": ["work.example"], "template_domains": True})
check("the built-in list is a direct list: dropped in tunnel mode", e is None and r["template_domains"] is False, (r, e))
check("everything at its default is no rule (absent)", V({"apps_mode": "all", "packages": ["x.y"]}) == (None, None) and V({}) == (None, None))
check("the built-in list alone is a rule", (V({"template_domains": True})[0] or {}).get("template_domains") is True)
# review of a897a710..2b7fe0ee (F3–F7, F9, F10)
r, e = V({"domains": ["госуслуги.рф", "*", "*."], "ips": ["192.168.1.10/24", "10.0.0.0/255.0.0.0", "10.1.2.3"]})
check("a Cyrillic domain is stored as punycode; a bare * is skipped, never a blank error",
      e is None and r["domains"] == ["xn--c1aapkosapc.xn--p1ai"], (r, e))
check("addresses are stored normalised (host bits cleared, netmask form as a prefix, a host bare)",
      e is None and r["ips"] == ["192.168.1.0/24", "10.0.0.0/8", "10.1.2.3"], (r, e))
r, e = V({"domains": ["1.2.3.4"]})
check("an address under Domains is refused, pointing to Addresses", r is None and e and "Addresses" in e["error"], (r, e))
for x in (["0.0.0.0/0"], ["0.0.0.0/1", "128.0.0.0/1"], ["0.0.0.0-255.255.255.255"]):
    r, e = V({"ips": x})
    check("%s as direct is refused (everything outside the tunnel)" % x, r is None and e and "outside the tunnel" in e["error"], (r, e))
check("…while as a tunnel-only address it is allowed", V({"ips_mode": "tunnel", "ips": ["0.0.0.0/0"]})[1] is None)
check("every app except none is every app: no rule", V({"apps_mode": "except", "packages": []}) == (None, None))
for bad in ("com.1app", "com._x", "a." + "b" * 300):
    r, e = V({"apps_mode": "except", "packages": [bad]})
    check("app ID %s… refused" % bad[:12], r is None and e and "Android app ID" in e["error"], (r, e))
# review of a897a710..fa484d42: the app's own grammar (F1, F2, F4, F6, F7, F9, F14–F16, F19)
for bad, key in (({"domains": ["*.ru"]}, "is not a domain"), ({"domains": ["рф"]}, "is not a domain"),
                 ({"domains": ["xn--a.ru"]}, "is not a domain"), ({"domains": ["foo.123"]}, "is not a domain"),
                 ({"domains": ["ya.ru\n."]}, "is not a domain"), ({"domains": ["10.0.0.256"]}, "Addresses"),
                 ({"ips": ["2001:db8::/32"]}, "IPv4"), ({"ips": ["fe80::1%x"]}, "IPv4"), ({"ips": ["10.0.0.9-10.0.0.1"]}, "IP address or range"),
                 ({"domains": {"ya.ru": 1}}, "not a valid setting"), ({"domains": [None]}, "not a valid setting"),
                 ({"template_domains": "false"}, "not a valid setting"), ({"domains": ["d%d.ru" % i for i in range(501)] * 2}, "at most")):
    r, e = V(bad)
    check("refused: %s → %s" % (str(bad)[:40], key), r is None and e and key in e["error"], (r, e))
# verify of fa484d42..b782d868 (F56, F58)
r, e = V({"domains": ["xn--e1aybc.xn--p1ai", "xn--zca.de", "xn--pple-43d.com"]})
check("a domain given as its wire name (punycode) is stored as given — the sheet may send one back",
      e is None and r["domains"] == ["xn--e1aybc.xn--p1ai", "xn--zca.de", "xn--pple-43d.com"], (r, e))
check("…an xn-- label that does not decode is refused", (V({"domains": ["xn--zz.ru"]})[1] or {}).get("error", "").find("is not a domain") > 0)
# verify round 2 (F59–F61): every form the sheet shows a stored name in comes back to it; junk xn-- refused
r, e = V({"domains": ["ß.de", "straße.de", "xn--pple-43d.рф", "аpple.рф", "Госуслуги.РФ"]})
check("a name is punycoded label by label as written (ß stays ß, a mixed-script label kept)",
      e is None and r["domains"] == ["xn--zca.de", "xn--strae-oqa.de", "xn--pple-43d.xn--p1ai", "xn--c1aapkosapc.xn--p1ai"], (r, e))
for x in ("xn--zca.de", "xn--strae-oqa.de", "xn--pple-43d.xn--p1ai", "xn--c1aapkosapc.xn--p1ai"):
    shown = ".".join((l[4:].encode().decode("punycode") if l.startswith("xn--") and l != "xn--pple-43d" else l) for l in x.split("."))
    check("stored %s, shown as %s, saves back unchanged" % (x, shown), V({"domains": [shown]})[0]["domains"] == [x], V({"domains": [shown]}))
r, e = V({"domains": "ya.ru;vk.com", "packages": "org.a.b;org.c.d", "apps_mode": "only", "ips": "1.2.3.4;5.6.7.8"})
check("\";\" separates entries, as in the app", e is None and r["domains"] == ["ya.ru", "vk.com"] and r["packages"] == ["org.a.b", "org.c.d"]
      and r["ips"] == ["1.2.3.4", "5.6.7.8"], (r, e))
r, e = V({"domains": "www.google.com https://ya.ru/x vk.com:443"})
check("www. dropped (the app applies the parent), a link's host kept, whitespace splits",
      e is None and r["domains"] == ["google.com", "ya.ru", "vk.com"], (r, e))

print("[2] delivery")
check("csqtt_cfg publishes app_routing", '"bind_ip", "line",\n' in open(PANEL).read() and '"app_routing", "app_routing_except") if k in ov}' in open(PANEL).read())
AR = {"apps_mode": "except", "packages": ["org.telegram.messenger"], "domains_mode": "direct", "domains": ["ya.ru"],
      "template_domains": True, "ips_mode": "direct", "ips": []}
nodes = {"n1": {"csqtt": {"csqtt1": {"listen": "0.0.0.0:46000", "tun_addr": "10.66.70.1/24", "app_routing": AR}}}}
P._turn_hold_get = lambda *a: None
try:
    rep = P._csqtt_reply({"users": {}, "peers": {}}, nodes, "n1", snap={"csqtt_lines": ["2.1", "2.5"]})
except Exception as ex:
    rep = {"error": repr(ex)}
check("the node's reply carries app_routing as stored", (rep.get("csqtt1") or {}).get("app_routing") == AR, rep)

print("[3] the node's desired.json")
PW = {"p1": {"name": "alice"}, "p2": {}}
B = lambda pw, ar=None: N._csqtt_desired_body({"passwords": pw, "app_routing": ar})
plain = B(PW)
check("no rule: byte-identical to the body before App routing",
      plain == json.dumps({"passwords": [{"password": "p1", "expires_at": 0, "vk_hash": "", "name": "alice", "is_deactivated": False},
                                         {"password": "p2", "expires_at": 0, "vk_hash": "", "name": "", "is_deactivated": False}]}), plain)
check("…and None / {} for the rule is the same", B(PW, None) == plain and B(PW, {}) == plain)
withr = json.loads(B(PW, dict(AR, bogus=1)))
check("the server's rule is carried, its known keys only", withr.get("app_routing") == AR, withr.get("app_routing"))
for bad in (dict(AR, packages="com.x"), dict(AR, domains=["ya.ru", 7]), dict(AR, apps_mode="sometimes"), "x"):
    check("a rule of the wrong shape is dropped whole: %s" % str(bad)[:50], "app_routing" not in json.loads(B(PW, bad)))

print("[4] the node's drift check")
TMP = tempfile.mkdtemp(prefix="csqtt-ar-")
N._csqtt_dir = lambda iface: TMP
open(os.path.join(TMP, "desired.json"), "w").write(B(PW, AR) + "\n")
check("the same rule: no change", N._csqtt_desired_changed("csqtt1", B(PW, AR)) is False)
check("a changed rule: a change", N._csqtt_desired_changed("csqtt1", B(PW, dict(AR, domains=["vk.com"]))) is True)
check("the rule removed: a change", N._csqtt_desired_changed("csqtt1", B(PW)) is True)

print("\n" + ("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS))))
sys.exit(1 if FAILS else 0)
