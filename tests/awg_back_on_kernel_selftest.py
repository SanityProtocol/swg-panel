#!/usr/bin/env python3
"""Runner for tests/awg_back_on_kernel_selftest.sh — the check itself is a sandboxed shell harness (it exercises update.sh /
lib/common.sh functions with stubbed system tools), kept in shell because that is the language it tests. This wrapper
exists so a runner that collects `tests/*_selftest.py` runs it too. Arguments (e.g. --perturb) pass through; the exit
code is the harness's.
"""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call(["bash", os.path.join(here, "awg_back_on_kernel_selftest.sh")] + sys.argv[1:]))
