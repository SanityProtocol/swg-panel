#!/usr/bin/env python3
"""Self-test for T-10 (Transfer) — the parts a rig cannot reach.

`.campaign/node-sync-rig.py` case [11] drives two real panels and asserts what a transfer does to them.
What it cannot touch is the NODE's half — the promotion is a decision `swg-noded` makes about a panel it
has never spoken to — and the two pure functions on the sending side, where the interesting inputs are the
ones an operator pastes by mistake.

Hermetic: no network, no panel, no state dir. Run:  python3 tests/transfer_selftest.py   (exit 0 = pass)
"""
import base64, importlib.machinery, importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def load(path, name, env=None):
    for k, v in (env or {}).items():
        os.environ[k] = v
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


_STATE = tempfile.mkdtemp(prefix="swg-xfer-selftest-")
S = load(SERVER, "swgpanel_xfer")
N = load(NODED, "swgnoded_xfer", env={"SWG_NODED_STATE": _STATE,
                                      "SWG_AGENT_CONFIG": os.path.join(_STATE, "config.json")})

BOOT = "https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh"

print("\n[1] the paste — only two of the five enrolment shapes can BE one (§3.2)")
g = S.transfer_parse("curl -fsSL %s | sudo bash -s node -key ABCDEFGHIJKLMNOP1234 -host https://p.example.org:8443" % BOOT)
check("the bare-metal one-liner yields url + token",
      g == {"url": "https://p.example.org:8443", "token": "ABCDEFGHIJKLMNOP1234", "kind": "baremetal"}, g)
g = S.transfer_parse("curl -fsSL %s | sudo bash -s docker node -key ABCDEFGHIJKLMNOP1234 -host https://p.example.org/swg" % BOOT)
check("the docker one-liner is recognised as docker, and a mount base survives",
      g["kind"] == "docker" and g["url"] == "https://p.example.org/swg", g)
g = S.transfer_parse("curl -fsSL %s | sudo bash -s node -key ABCDEFGHIJKLMNOP1234 -host p.example.org" % BOOT)
check("a bare host is read as https — never as an unencrypted push", g["url"] == "https://p.example.org", g)


# ── the TRANSFER TOKEN: the shape the Transfer window actually asks for ───────────────────────
# One value carrying the target's address and a key valid there, minted in the browser. It exists because
# the enrolment COMMAND was the wrong thing to ask for: it is a carrier for these same two values, and the
# declarative (NixOS) shape has no `-key` in it at all.
def xtok(url, token, kind=""):
    raw = json.dumps({"u": url, "t": token, "k": kind}).encode()
    return "swgx1_" + base64.urlsafe_b64encode(raw).decode().rstrip("=")

def parsed(text):
    """…as a VALUE, never as an exception. A positive check that raises aborts the file, so one regression
    here would hide every check after it — including the refusals, which are the half that protects."""
    try:
        return S.transfer_parse(text)
    except Exception as e:
        return {"url": None, "token": None, "kind": None, "raised": str(e)}

g = parsed(xtok("https://p.example.org:8443", "ABCDEFGHIJKLMNOP1234"))
check("a transfer token yields the same url + token a command would",
      g["url"] == "https://p.example.org:8443" and g["token"] == "ABCDEFGHIJKLMNOP1234", g)
g = parsed(xtok("https://p.example.org/swg", "ABCDEFGHIJKLMNOP1234"))
check("...with a mount base preserved", g["url"] == "https://p.example.org/swg", g)
g = parsed("  " + xtok("p.example.org", "ABCDEFGHIJKLMNOP1234") + "\n")
check("...surviving the whitespace a paste brings, and defaulting to https",
      g["url"] == "https://p.example.org", g)
check("...and claiming no install kind, because a transfer installs nothing", g["kind"] == "", g)


def refuses(text, frag):
    try:
        S.transfer_parse(text)
        return False, "parsed"
    except S.TransferError as e:
        return (frag.lower() in str(e).lower()), str(e)

ok, why = refuses("sudo install -d -m 700 /etc/swg-secrets\n"
                  "printf %s 'TOKENTOKENTOKENTOKEN' | sudo tee /etc/swg-secrets/swg-node-token >/dev/null",
                  "declarative")
check("the NixOS native shape is refused BY NAME — it carries no -key at all", ok, why)
ok, why = refuses("printf 'NODE_TOKEN=%s\\n' 'TOKENTOKENTOKENTOKEN' | sudo tee /etc/swg-secrets/swg-node.env",
                  "declarative")
check("...and so is the podman one", ok, why)
ok, why = refuses('{ services.swg-node = { enable = true; panelUrl = "https://p"; '
                  'tokenFile = "/etc/swg-secrets/swg-node-token"; }; }', "declarative")
check("...and the flake block, which carries the URL but no token", ok, why)
ok, why = refuses("", "transfer token")
check("an empty paste says what to paste", ok, why)
ok, why = refuses("swgx1_" + "!!!!not-base64!!!!", "looks like a transfer token")
check("a mangled token is answered AS a token, not as 'that is not a command'", ok, why)
ok, why = refuses(xtok("https://p.example.org", "short"), "no usable node key")
check("a token carrying too short a key is refused, not passed to the far panel", ok, why)
ok, why = refuses(xtok("", "ABCDEFGHIJKLMNOP1234"), "no usable panel address")
check("...and one carrying no address says so", ok, why)
ok, why = refuses("swgx1_" + base64.urlsafe_b64encode(b"not json at all").decode().rstrip("="), "damaged")
check("...and one whose payload is not readable says THAT, rather than blaming the operator", ok, why)
ok, why = refuses("curl -fsSL %s | sudo bash -s node -host https://p.example.org" % BOOT, "-key")
check("a command with no -key names what is missing", ok, why)
ok, why = refuses("curl -fsSL %s | sudo bash -s node -key ABCDEFGHIJKLMNOP1234 -host ///" % BOOT, "usable address")
check("an unusable -host is refused rather than half-parsed", ok, why)

print("\n[2] the strip — a Transfer crosses a VAULT, and a rebuild does not")
REC = {"id": "n1", "name": "edge-01", "endpoint_host": "edge.example.org", "mesh_gen": 3,
       "token_hash": "pbkdf2_sha256$1$x", "token_sha": "aa" * 32,
       "superseded_box": {"token_hash": "old"}, "rebuild": {"at": 1}, "create": {"awg0": {}},
       "fp": {"baselines": [{"id": "b1"}]},
       "links": {"l1": {"psk": "MESHPSK", "iface": "wgm1"}},
       "ifaces": {"awg0": {"public_key": "SRVPUB", "listen_port": 51820,
                           "key_blob": {"pub": "SRVPUB", "vault": "V-A"},
                           "_synced": {"mtu": 1420}, "_drift": {}},
                  # a mesh-managed link, exactly as every node on the live fleet carries two of
                  "swg_3be755fd": {"system": True, "link_id": "l1", "public_key": "MESHPUB"}},
       "wdtt": {"wdtt1": {"fork": "amurcanov", "key_blob": {"pub": "W", "vault": "V-A"}}},
       "csqtt": {"csqtt1": {"listen": "0.0.0.0:46000"}}}
clean, stripped = S.transfer_strip(json.loads(json.dumps(REC)))
check("every sealed key is stripped, in all three places it can live",
      "key_blob" not in clean["ifaces"]["awg0"] and "key_blob" not in clean["wdtt"]["wdtt1"], clean)
check("...and each one is NAMED, so the pre-flight can say what does not travel",
      sorted((x["kind"], x["iface"]) for x in stripped) == [("iface", "awg0"), ("wdtt", "wdtt1")], stripped)
check("the mesh does not travel — its links belong to the fleet being left",
      "links" not in clean, clean.get("links"))
check("...BOTH halves of it: the mesh-managed INTERFACE records go with the links",
      "swg_3be755fd" not in clean["ifaces"] and "awg0" in clean["ifaces"], sorted(clean["ifaces"]))
check("...but the mesh GENERATION does, so the far panel can name new links past the running ones",
      clean.get("mesh_gen") == 3, clean.get("mesh_gen"))
check("the lockout bookkeeping does not travel", not any(k in clean for k in
      ("token_hash", "token_sha", "superseded_box")), sorted(clean))
check("...nor the in-flight acks, nor the stored baselines",
      not any(k in clean for k in ("create", "rebuild", "fp")), sorted(clean))
check("...nor the convergence state, which the far panel rebuilds by syncing",
      "_synced" not in clean["ifaces"]["awg0"] and "_drift" not in clean["ifaces"]["awg0"],
      clean["ifaces"]["awg0"])
check("everything else is MIRRORED — the default is carry, not drop",
      clean["ifaces"]["awg0"] == {"public_key": "SRVPUB", "listen_port": 51820}
      and clean["endpoint_host"] == "edge.example.org" and clean["csqtt"] == REC["csqtt"], clean)
check("⚠️ the input is NOT mutated — the caller's record is still the panel's own",
      "key_blob" in REC["ifaces"]["awg0"], REC["ifaces"]["awg0"])
# The one distinction §3.2 spells out: `key_blob` is KEPT by a rebuild and STRIPPED by a transfer.
kept, _acts = S.fp_transform(json.loads(json.dumps(REC)), "rebuild", {"before_ips": [], "after_ips": []})
check("⚠️ …and a REBUILD keeps the sealed key — the two must not share a helper",
      "key_blob" in (kept.get("ifaces") or {}).get("awg0", {}), kept.get("ifaces"))

print("\n[3] the sections a moving roster needs (§2)")
check("a rebuild is judged on the two sections it can move",
      S.fp_sections("rebuild") == ("residue", "render"), S.fp_sections("rebuild"))
check("a transfer adds intent and external", S.fp_sections("transfer")
      == ("residue", "render", "intent", "external"), S.fp_sections("transfer"))
check("an unknown op still gets sections — never an empty capture that diffs clean",
      S.fp_sections("nonsense") == ("residue", "render"), S.fp_sections("nonsense"))
ROSTER = {"users": {"u1": {"name": "alice"}},
          "peers": {"p1": {"user_id": "u1", "title": "laptop", "pubkey": "K1", "psk": "PSK1",
                           "targets": [{"node": "n1", "iface": "awg0", "ip": "10.0.0.5", "type": "awg"}]},
                    "p2": {"user_id": "u1", "title": "phone", "pubkey": "K2", "psk": "PSK2",
                           "targets": [{"node": "n1", "iface": "awg0", "ip": "10.0.0.6", "type": "awg"}]}}}
i1 = S._fp_intent_for_node({}, {"n1": REC}, "n1", ROSTER)
r2 = {"users": ROSTER["users"], "peers": {k: ROSTER["peers"][k] for k in ("p2", "p1")}}
i2 = S._fp_intent_for_node({}, {"n1": REC}, "n1", r2)
check("`intent` is keyed by public key, so two panels holding the same peers agree byte-for-byte",
      S._fp_hash(i1) == S._fp_hash(i2), (sorted(i1.get("awg0", {})), sorted(i2.get("awg0", {}))))
check("...and it carries the PSK as an identity, never as a secret",
      i1["awg0"]["K1"]["preshared_key"] == S._fp_secret("psk", "PSK1"), i1["awg0"]["K1"])
check("...while a DIFFERENT peer set moves the hash", S._fp_hash(i1) != S._fp_hash(
      S._fp_intent_for_node({}, {"n1": REC}, "n1", {"users": ROSTER["users"],
                                                    "peers": {"p1": ROSTER["peers"]["p1"]}})))
e1 = S._fp_external({"panel_settings": {"vk_link": "https://vk.example/me"}, "fleet": {}})
e2 = S._fp_external({"panel_settings": {"vk_link": "https://vk.example/someone-else"}, "fleet": {}})
check("`external` carries the panel-wide VK fallback as an identity, and it MOVES between panels",
      e1["vk_link"] and e1["vk_link"] != e2["vk_link"], (e1["vk_link"], e2["vk_link"]))
check("...and never the link itself, because the tree is stored on disk as a baseline",
      "vk.example" not in json.dumps(e1), e1)

print("\n[4] the node's half — the re-point is a CANDIDATE until the far panel answers")
CALLS = []
def fake_verify(ok_for):
    def _v(url, token, panel):
        CALLS.append({"url": url, "token": token, "verify": bool(panel.get("verify")),
                      "fp": panel.get("fingerprint") or ""})
        return ok_for(url, token, panel)
    return _v

def promote(cand, ok_for, panel=None):
    CALLS.clear()
    N._XFER["cand"] = dict(cand) if cand else None
    p = panel if panel is not None else {"url": "https://a.example", "token": "TOK-A",
                                         "verify": False, "fingerprint": "aa" * 32}
    cfg = {"panel": dict(p)}
    _orig = N._verify_panel
    N._verify_panel = fake_verify(ok_for)
    try:
        return N._promote_transfer(p, cfg), p
    finally:
        N._verify_panel = _orig

CAND = {"url": "https://b.example", "token": "TOK-B", "fp": "bb" * 32, "verify": False}
out, p = promote(CAND, lambda u, t, pn: False)
check("a target that never answers does NOT take the node — nothing is lost", out is None
      and p["url"] == "https://a.example" and p["token"] == "TOK-A", (out, p))
check("...and the candidate is KEPT, so the next pass tries again", N._XFER["cand"] is not None)
check("...and it was tried under BOTH postures, verified first then pinned",
      [c["verify"] for c in CALLS] == [True, False] and CALLS[1]["fp"] == "bb" * 32, CALLS)
out, p = promote(CAND, lambda u, t, pn: bool(pn.get("verify")))
check("a CA-verified target is adopted with no pin at all", out == "https://b.example/api/node/sync"
      and p["verify"] is True and "fingerprint" not in p, (out, p))
check("...with the far panel's OWN token, which is the whole point of the exchange",
      p["token"] == "TOK-B" and p["url"] == "https://b.example", p)
check("...and the candidate is consumed", N._XFER["cand"] is None)
out, p = promote(CAND, lambda u, t, pn: pn.get("fingerprint") == "bb" * 32)
check("a self-signed target is adopted ONLY against the certificate the sending panel saw",
      out and p["fingerprint"] == "bb" * 32 and p["verify"] is False, (out, p))
out, p = promote({**CAND, "fp": ""}, lambda u, t, pn: not pn.get("verify"))
check("⚠️ …and with no fingerprint to pin, an unverifiable target is NOT adopted on trust",
      out is None, (out, p))
check("the promotion mirrors the credential beside the URL — a container recreate must not undo it",
      os.path.exists(os.path.join(_STATE, "panel-token")), sorted(os.listdir(_STATE)))

_learn = lambda reply, panel=None: (N._learn_transfer(panel or {"url": "https://a.example"}, reply),
                                    N._XFER["cand"])[1]
N._persist_transfer(None)
check("a sync reply carrying no transfer leaves no candidate", _learn({}) is None)
c = _learn({"transfer": {"url": "https://b.example", "token": "TOK-B", "fp": "CC" * 32, "verify": False}})
check("...one that does is learned, and the fingerprint normalised", (c or {}).get("fp") == "cc" * 32, c)
check("...and it SURVIVES A RESTART — a transfer must not be lost to a reboot mid-flight",
      (N._XFER.update({"cand": None}), N._load_transfer(), (N._XFER["cand"] or {}).get("token"))[2] == "TOK-B")
check("⚠️ …and the panel withdrawing it drops it — a cancelled transfer must not leave another "
      "fleet's credential on the box", _learn({}) is None)
check("a candidate naming the panel we already dial is not a transfer at all",
      _learn({"transfer": {"url": "https://a.example/", "token": "X", "fp": "", "verify": True}}) is None)

import shutil
shutil.rmtree(_STATE, ignore_errors=True)
print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("ALL PASS")
