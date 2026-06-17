#!/usr/bin/env python3
"""Standalone test for swg-noded's node-health collection — no node, no pytest, stdlib only.

Builds a fake /proc tree and checks collect_health() parses it correctly, including the
MemAvailable→MemFree fallback for old kernels. Disk is checked against a real temp dir
(statvfs works on any path). Run: `python3 tests/test_health.py` (exit 0 = pass)."""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_noded():
    path = os.path.join(ROOT, "swg-noded")
    loader = importlib.machinery.SourceFileLoader("swg_noded", path)
    spec = importlib.util.spec_from_loader("swg_noded", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def write_fixture(proc):
    os.makedirs(proc)
    with open(os.path.join(proc, "loadavg"), "w") as f:
        f.write("0.50 0.75 1.00 2/345 6789\n")
    with open(os.path.join(proc, "uptime"), "w") as f:
        f.write("123456.78 987654.00\n")
    with open(os.path.join(proc, "meminfo"), "w") as f:
        f.write("MemTotal:       16331156 kB\n"
                "MemFree:         1048576 kB\n"
                "MemAvailable:    8165578 kB\n"
                "Buffers:          200000 kB\n"
                "SwapTotal:       2000000 kB\n"
                "SwapFree:        1500000 kB\n")
    with open(os.path.join(proc, "stat"), "w") as f:
        f.write("cpu  100 0 50 900 0 0 0\n"
                "cpu0 25 0 12 225 0 0 0\n"
                "cpu1 25 0 12 225 0 0 0\n"
                "cpu2 25 0 13 225 0 0 0\n"
                "cpu3 25 0 13 225 0 0 0\n"
                "intr 12345\n")


def main():
    h = load_noded()
    tmp = tempfile.mkdtemp()
    proc = os.path.join(tmp, "proc")
    write_fixture(proc)

    out = h.collect_health(proc_root=proc, mounts=[tmp])

    assert out["load"] == [0.5, 0.75, 1.0], out["load"]
    assert out["ncpu"] == 4, out["ncpu"]
    assert out["mem"]["total"] == 16331156 * 1024, out["mem"]
    assert out["mem"]["available"] == 8165578 * 1024, out["mem"]
    assert out["mem"]["used"] == (16331156 - 8165578) * 1024, out["mem"]
    assert out["mem"]["swap_total"] == 2000000 * 1024, out["mem"]
    assert out["mem"]["swap_used"] == (2000000 - 1500000) * 1024, out["mem"]
    assert round(out["uptime"]) == 123457, out["uptime"]
    assert out["disk"] and out["disk"][0]["mount"] == tmp, out["disk"]
    assert out["disk"][0]["total"] > 0 and out["disk"][0]["used"] >= 0, out["disk"]
    assert out["disk"][0]["free"] >= 0, out["disk"]

    # MemAvailable absent (old kernel) -> falls back to MemFree; no mounts -> no disk key.
    with open(os.path.join(proc, "meminfo"), "w") as f:
        f.write("MemTotal:        1000000 kB\nMemFree:          400000 kB\n")
    out2 = h.collect_health(proc_root=proc, mounts=[])
    assert out2["mem"]["available"] == 400000 * 1024, out2["mem"]
    assert out2["mem"]["used"] == 600000 * 1024, out2["mem"]
    assert "swap_total" not in out2["mem"], out2["mem"]
    assert "disk" not in out2, out2

    # A broken /proc must not raise — each field is independent.
    out3 = h.collect_health(proc_root=os.path.join(tmp, "nope"), mounts=[])
    assert isinstance(out3, dict), out3

    print("OK test_health: all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
