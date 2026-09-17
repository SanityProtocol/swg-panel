#!/usr/bin/env python3
"""A minimal DevTools-protocol client for the browser gates: headless Chrome driven over --remote-debugging-pipe.

No dependency: the protocol on a pipe is NUL-delimited JSON, commands written to the browser's fd 3 and answers read from its
fd 4. Used by tests/sub_page_render_selftest.py (the subscription page) and tests/spa_render_selftest.py (the operator app).
Not a selftest itself — the runner only picks up *selftest* files.
"""
import fcntl, json, os, select, shutil, subprocess, tempfile, time

CHROME = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


class Browser:
    def __init__(self):
        cr, cw = os.pipe(); rr, rw = os.pipe()
        hi = lambda fd: fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 20)   # above 4, so the dup2 onto 3/4 below cannot clobber one
        self._cr, self._rw, self.w, self.r = hi(cr), hi(rw), hi(cw), hi(rr)
        for fd in (cr, cw, rr, rw):
            os.close(fd)
        self.prof = tempfile.mkdtemp(prefix="cdp-chrome-")
        cr_, rw_ = self._cr, self._rw
        def pre():
            os.dup2(cr_, 3); os.dup2(rw_, 4)
        self.p = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-pipe", "--no-first-run", "--no-default-browser-check",
                                   "--disable-gpu", "--disable-extensions", "--user-data-dir=" + self.prof, "about:blank"],
                                  preexec_fn=pre, pass_fds=(3, 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(self._cr); os.close(self._rw)
        self.buf, self.mid, self.events = b"", 0, []

    def _read(self, t):
        while b"\0" not in self.buf:
            r, _, _ = select.select([self.r], [], [], max(0.01, t))
            if not r:
                return None
            chunk = os.read(self.r, 1 << 20)
            if not chunk:
                raise EOFError("the browser closed its pipe")
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\0", 1)
        return json.loads(raw)

    def send(self, method, params=None, session=None, timeout=30):
        self.mid += 1
        mid = self.mid
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.w, json.dumps(msg).encode() + b"\0")
        end = time.time() + timeout
        while time.time() < end:
            m = self._read(end - time.time())
            if m is None:
                continue
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError("%s: %s" % (method, m["error"]))
                return m.get("result", {})
            self.events.append(m)
        raise TimeoutError(method)

    def pump(self, secs):
        end = time.time() + secs
        while time.time() < end:
            m = self._read(end - time.time())
            if m is not None:
                self.events.append(m)

    def close(self):
        try:
            self.send("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()
        shutil.rmtree(self.prof, ignore_errors=True)


class Tab:
    def __init__(self, br):
        self.br = br
        tid = br.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.s = br.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            br.send(m, session=self.s)
        # A binding outlives navigations — the page's own record would not: a one-tap Start that finds no app falls back to
        # the download page and REPLACES the document, taking an in-page log of what was copied with it.
        br.send("Runtime.addBinding", {"name": "__swgClip"}, session=self.s)
        self.tid = tid

    def ev(self, expr, timeout=30):
        r = self.br.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, session=self.s, timeout=timeout)
        if r.get("exceptionDetails"):
            raise RuntimeError("evaluate: %s" % json.dumps(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")

    def goto(self, url):
        self.br.send("Page.navigate", {"url": url}, session=self.s)

    def mine(self, method):
        return [e for e in self.br.events if e.get("sessionId") == self.s and e.get("method") == method]

    def close(self):
        try:
            self.br.send("Target.closeTarget", {"targetId": self.tid}, timeout=10)
        except Exception:
            pass
