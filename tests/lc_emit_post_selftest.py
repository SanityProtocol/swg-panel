#!/usr/bin/env python3
"""Runner for tests/lc_emit_post_selftest.sh — the check itself is a shell harness (it runs lib/common.sh's lc_emit_post
against a stub curl), kept in shell because that is the language it tests. This wrapper exists so a runner that collects
`tests/*_selftest.py` runs it too. Arguments (e.g. --perturb) pass through; the exit code is the harness's.
"""
import os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call(["bash", os.path.join(here, "lc_emit_post_selftest.sh")] + sys.argv[1:]))
