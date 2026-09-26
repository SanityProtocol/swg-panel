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
