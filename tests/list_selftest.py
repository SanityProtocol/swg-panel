#!/usr/bin/env python3
"""Data-plane self-test for the panel's list resolution — the one regression guard for a system with no test suite.

Locks the invariant that MATTERS: resolving a given input produces a byte-identical output (same domains, same order,
same version hash) whichever code path builds it — the streaming host resolver, the in-memory normalizers, and the
union merge must all agree. A drift here silently misroutes or mis-blocks traffic, so this asserts:

  1. streaming host resolve  ==  in-memory normalizer   (per format: plain / hosts / abp / classical)  + golden hash
  2. union (heapq.merge)     ==  sorted(set(members))                                                    + golden hash
  3. ip normalize            collapses overlaps and honours the size cap
  4. a 500k-domain list resolves under a hard RSS ceiling (the streaming memory bound that fixed the OOM)

Hermetic: fixtures are fed via file:// URLs, no network. Run:  python3 tests/list_selftest.py   (exit 0 = all pass)
"""
import importlib.machinery, importlib.util, os, sys, tempfile, hashlib, resource

HERE = os.path.dirname(os.path.abspath(__file__))
# default to the repo copy next to this file; SWG_PANEL_SERVER lets you point it at a DEPLOYED binary (e.g. /opt/swg-panel/swg-panel-server)
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(HERE, "..", "swg-panel-server")

def load():
    loader = importlib.machinery.SourceFileLoader("swgpanel", os.path.abspath(SERVER))
    spec = importlib.util.spec_from_loader("swgpanel", loader)
    m = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(m)
    except SystemExit:
        pass
    return m

def bodyhash(items):
    return hashlib.sha1(("\n".join(items) + ("\n" if items else "")).encode()).hexdigest()[:12]

def filehash(path):
    return hashlib.sha1(open(path, "rb").read()).hexdigest()[:12]

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

# ── fixtures: one tricky sample per format (comments, wildcards, dups, case, invalid, exceptions) ──
FIX = {
 "plain": ("ads.example.com\n+.track.evil.net\n*.wild.card\n.leading.dot\nADS.EXAMPLE.COM\n# comment\n\nnot a domain\n"
           "ads.example.com   # trailing\nxn--80ak6aa92e.com\nlocalhost\n1.2.3.4\n"),
 "hosts": ("0.0.0.0 ads.tracker.io\n127.0.0.1 spy.co # c\nbare.domain.org\n0.0.0.0 localhost\n:: nope\n"
           "0.0.0.0 ADS.tracker.io\n# header\n\n0.0.0.0\n"),
 "abp":   ("! title\n||ads.doubleclick.net^\n||track.me^$third-party\n@@||allow.me^\ncosmetic.com##.ad\n"
           "||REGEX/bad/\n||dup.net^\n||dup.net^\n||has*star.com^\n||ok.example.org^\n"),
 "classical": ("# clash\nDOMAIN,exact.example.com\nDOMAIN-SUFFIX,suffix.example.net\nDOMAIN-KEYWORD,drop\n"
               "IP-CIDR,1.2.3.0/24\nDOMAIN,EXACT.example.com\nPROCESS-NAME,x\nDOMAIN-SUFFIX,suffix.example.net\n"),
}
LINE = {}  # filled after load

def stream_resolve(m, tier, url, line_fn):
    d = tempfile.mkdtemp()
    old = m.LIST_DIR; m.LIST_DIR = d
    try:
        meta, st = m._stream_host_store("selftest:x", tier, url, line_fn)
        return filehash(m._list_path("selftest:x", tier)), meta.get("n"), st
    finally:
        m.LIST_DIR = old
        import shutil; shutil.rmtree(d, ignore_errors=True)

def main():
    m = load()
    LINE.update({"plain": m._line_host_plain, "hosts": m._line_hosts, "abp": m._line_abp, "classical": m._line_classical_host})
    NORM = {"plain": m._norm_host_plain, "hosts": m._norm_hosts, "abp": m._norm_abp,
            "classical": lambda t: m._norm_classical(t, "host")}
    tmp = tempfile.mkdtemp()

    print("[1] streaming host resolve == in-memory normalizer == pinned golden hash")
    # Pinned golden output hashes for the fixtures above. Self-check (stream==inmemory) catches DIVERGENCE between the
    # two paths; the golden catches a change that moves BOTH consistently. A deliberate normalizer change updates these.
    GOLDEN_HOST = {"plain": "a51fdfdee2e6", "hosts": "d51487b80ee0", "abp": "3c7e6fe6136d", "classical": "7356abbe691c"}
    for fmt, text in FIX.items():
        fp = os.path.join(tmp, fmt + ".txt"); open(fp, "w").write(text)
        ref = bodyhash(NORM[fmt](text))
        sh, n, st = stream_resolve(m, "host", "file://" + fp, LINE[fmt])
        check("%-9s stream==inmemory==golden" % fmt, ref == sh == GOLDEN_HOST[fmt],
              "ref=%s stream=%s golden=%s" % (ref, sh, GOLDEN_HOST[fmt]))

    print("[2] union heapq.merge == sorted(set(members)) (+ dedup across members)")
    d = tempfile.mkdtemp(); old = m.LIST_DIR; m.LIST_DIR = d
    try:
        a = os.path.join(tmp, "ma.txt"); open(a, "w").write("ads.example.com\ntrack.evil.net\nzzz.last.org\n")
        b = os.path.join(tmp, "mb.txt"); open(b, "w").write("ads.example.com\nporn.xxx\naaa.first.org\n")
        m._stream_host_store("blk:t:a", "host", "file://" + a, m._line_host_plain)
        m._stream_host_store("blk:t:b", "host", "file://" + b, m._line_host_plain)
        srcs = ["blk:t:a", "blk:t:b"]; key = m._blku_key("host", srcs); m._BLKU_REG[key] = sorted(srcs)
        umeta, ust = m._blku_store(key, "host")
        uhash = filehash(m._list_path(key, "host"))
        allm = set()
        for sid in srcs:
            for ln in open(m._list_path(sid, "host")):
                if ln.strip(): allm.add(ln.strip())
        ref = bodyhash(sorted(allm))
        check("union==sorted(set)", uhash == ref, "u=%s ref=%s" % (uhash, ref))
        check("union deduped", umeta.get("n") == len(allm), "n=%s want=%s" % (umeta.get("n"), len(allm)))
    finally:
        m.LIST_DIR = old; import shutil; shutil.rmtree(d, ignore_errors=True)

    print("[3] ip normalize: collapse + cap")
    ipn = m._norm_ip("1.2.3.0/24\n1.2.4.0/24\n1.2.3.128/25\n# c\n10.0.0.0/8\nbad\n::1\n")
    check("ip collapse (adjacent+subsumed)", ipn == ["1.2.3.0/24", "1.2.4.0/24", "10.0.0.0/8"], str(ipn))
    save = m._IP_NET_CAP; m._IP_NET_CAP = 2
    check("ip cap rejects oversize", m._norm_ip("1.0.0.0/32\n2.0.0.0/32\n3.0.0.0/32\n") is None)
    m._IP_NET_CAP = save

    print("[4] streaming RSS bound: 500k-domain list under ceiling")
    big = os.path.join(tmp, "big.txt")
    with open(big, "w") as f:
        for i in range(500000):
            f.write("host%06d.bulk.example.com\n" % i)
    r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    sh, n, st = stream_resolve(m, "host", "file://" + big, m._line_host_plain)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    check("500k resolve ok (n=%d)" % (n or 0), n == 500000 and st == "ok")
    check("peak RSS < 150MB (was ~150MB just for the 500k set)", peak < 150, "peak=%.0fMB (baseline %.0f)" % (peak, r0))
    print("     resolve peak RSS = %.0f MB" % peak)

    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS)); sys.exit(1)
    print("ALL PASS")

if __name__ == "__main__":
    main()
