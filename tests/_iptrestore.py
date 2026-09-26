"""Shared by the gates that model iptables: an `iptables-restore --noflush` input, as the `iptables -t <table> …` argv lists
it stands for.

The Kernel SNI chain is rebuilt in ONE restore transaction (1.8.8 qualification: rule by rule it took 211 s on msk-main,
unhooked all the while). A gate whose model read the chain from `iptables -A` calls would see an empty chain — and pass
or fail for the wrong reason. Declaring a chain under --noflush empties it (measured on iptables-nft 1.8.10), so a
declaration becomes -N (create if absent) + -F; every rule line is split the way the restore parser splits it
(double quotes, backslash escapes — POSIX shlex agrees on both)."""
import shlex


def restore_to_calls(text):
    calls, table = [], "filter"
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "COMMIT":
            continue
        if line.startswith("*"):
            table = line[1:].strip()
            continue
        if line.startswith(":"):
            ch = line[1:].split()[0]
            calls.append(["iptables", "-t", table, "-N", ch])
            calls.append(["iptables", "-t", table, "-F", ch])
            continue
        calls.append(["iptables", "-t", table] + shlex.split(line))
    return calls


def flatten(rules, chain="SWGK"):
    """The Kernel SNI chain is a DISPATCHER now (1.8.8 qualification: one jump per source into `SWGK_<n>`, so a packet
    walks its own source's rules alone). Gates written against the flat chain read it back flat: each `-j SWGK_<n>`
    jump is replaced, in place, by that chain's rules — renamed to `chain` — so ORDER checks still read the order a
    packet meets. `rules` are argv lists starting at "-A" (["-A", chain, ...])."""
    by = {}
    for r in rules:
        if len(r) > 1 and r[0] == "-A":
            by.setdefault(r[1], []).append(r)
    out = []
    for r in by.get(chain, []):
        tgt = r[r.index("-j") + 1] if "-j" in r else ""
        if tgt.startswith(chain + "_") and tgt in by:
            out += [["-A", chain] + x[2:] for x in by[tgt]]
        else:
            out.append(r)
    return out
