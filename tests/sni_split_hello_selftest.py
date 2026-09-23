#!/usr/bin/env python3
"""Self-test — swg-sni reads a ClientHello that spans TCP segments, is handed only the ClientHello, and sleeps when idle.

Chrome's ClientHello is ~2 KB since its X25519MLKEM768 key share (1 263 bytes), so it always takes two TCP segments, and
Chrome shuffles its extensions: in 15 of 27 captured (Chrome 152, 2026-09-23) the SNI lay past the first 1 340 bytes — a
WireGuard tunnel's MSS — and swg-sni, which parsed one segment, learned nothing from those connections. Meanwhile the
queue rule handed it every client packet until the connection had seen 12 (4.5 a connection, up to 6 for Chrome), each a
wake-up costing ~70–130 µs on a quiet 1-vCPU node, and its flusher woke 40 times a second with nothing to write.

The fixtures are three real Chrome 152 ClientHellos from a headless Chrome with a throwaway profile (ephemeral key shares,
nothing else): two whose SNI is past byte 1 340, one whose SNI is inside it.

  THE HELLO (Classifier.on_packet; nft stubbed)
    [1] the fixtures are what they claim: a one-segment parse of the first 1 340 bytes finds no name; of the whole, the host
    [2] the name in the 2nd segment: the 1st teaches nothing and is not reset; the 2nd completes the hello — the address is
        queued for its category, and the reset goes out on the 2nd
    [3] the name in the 1st segment: learned (and reset) there; the 2nd teaches nothing more and nothing is left held
    [4] a segment that does not fit the held hello (a gap) is not joined — and the hello is KEPT for the one that does
    [5] one that comes after PARTIAL_TTL is not joined
    [6] held hellos are bounded — PARTIAL_MAX flows — and the timed-out ones make room; [6b] one client holds at most
        PARTIAL_PER_SRC, and another client still gets a slot
    [7] a hello in three segments (a small MSS) is learned on the 3rd
    [8] a sequence number that wraps at 2^32 still joins
    [9] data that is not a ClientHello is never held; [9b] a retransmitted 1st segment between the two still joins;
        [9c] a re-cut 2nd segment that overlaps the 1st joins; [9d] a retransmit after the 2nd of three does not cut
        what is held
  THE FLUSHER (its real loop, nft stubbed)
    [10] idle, it does not poll (it woke 40 times a second)
    [11] the first learn after a quiet spell is written at once
    [12] a stream of learns is written FLUSH_INTERVAL apart — the batching is kept
    [12b] idle, a chore is done when it is due (the blocked-hits mirror), not up to IDLE_WAKE late
  THE QUEUE (swg-noded)
    [13] every rule that queues to swg-sni ends with `_sni_queue()`, none is hand-written, the match is the ClientHello's
         (data, before the server has answered, within the client's first 15 packets), and a node running swg-sni
         re-signs (`q2`), no other
    [14] through the nft model: a bare ACK is not queued; a ClientHello's segments are — the 1st retransmitted as the
         client's 5th packet too (the first cut, `ct original packets < 5`, lost that), a 5-byte tail, a segment after
         the server's SACKs; nothing after the server's flight, a resumed one's too (the second cut, `ct reply bytes <
         1000`, queued its Finished and request); nothing past the client's 15th packet
  FROM THE REVIEW OF THE FIXES
    [15] a held hello waits PARTIAL_TTL for its NEXT segment: each addition renews it and moves it to the back of the
         table; [15b] a 2nd segment 3 s after the 1st (a retransmit on a slow path) still joins
    [16] a segment that names its host by itself ends whatever was held for its flow, and frees its client's slot
    [17] with no traffic, the flusher's prune drops the timed-out held hellos
    [18] the blocked-hits mirror: a hit with nothing to learn wakes the flusher; an unchanged mirror is not rewritten;
         one that could not be written is tried again
    [19] idle, the flusher wakes once per chore — its own times are one clock

Run: python3 tests/sni_split_hello_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own section (exit 0 when caught):
     noreasm   a hello is parsed one segment at a time again                        [2]
     noseq     a segment is joined wherever it falls in the stream                  [4]
     nottl     a held hello never times out                                          [5]
     nocap     held hellos are not bounded                                           [6]
     nosrc     one client may hold them all                                          [6b]
     nowrap    the stream offset does not wrap at 2^32                               [8]
     noretx    a retransmit of what is held replaces it                              [9d]
     poll      the flusher wakes every FLUSH_INTERVAL again                          [10]
     nowake    the first learn is not announced to the flusher                       [11]
     nospace   writes are not kept FLUSH_INTERVAL apart                              [12]
     latechore idle, the flusher sleeps IDLE_WAKE whatever is due                    [12b]
     oldqueue  the queue gate is `ct packets < 12` again                             [13]
     handqueue one rule queues with its own hand-written match                       [13]
     lt5       the first cut: `ct original packets < 5`, no reply condition         [14]
     noreply   no reply condition: the client's Finished and request are queued too [14]
     bytes     the second cut: `ct reply bytes < 1000` (a resumed flight is smaller) [14]
     len64     `meta length > 64` again: a tail under 13 bytes is not queued        [14]
     norenew   an addition does not renew the held hello's wait                     [15]
     ttl2      PARTIAL_TTL is 2 s again                                             [15b]
     nodrophold a hello held for a flow outlives the segment that named its host    [16]
     nosweep   only a packet sweeps the held hellos                                 [17]
     noblkwake a blocked hit does not wake the flusher                              [18]
     blkstays  the mirror stays dirty once written (rewritten while unchanged)      [18]
     blknoretry a mirror that failed to write is not tried again                    [18]
     wallclock the flusher aims its sleep with the wall clock                       [19]
"""
import base64, collections, importlib.machinery, importlib.util, os, socket, struct, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SNI = os.environ.get("SWG_SNI") or os.path.join(ROOT, "swg-sni")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


Q = '"ct", "original", "packets", "lt", "16",\n            "ct", "reply", "avgpkt", "lt", "81", "meta", "length", "gt", "52", "queue"'
PLANTS = {   # name: (section it must redden, file, anchor, replacement) — Q: the queue match's tail, as swg-noded writes it
    "noreasm": ("[2]", "sni", "            host = self._reassemble(payload, tcp)\n", "            host = None\n"),
    "noseq": ("[4]", "sni", "                if off <= len(buf):                                  # it continues, or overlaps",
              "                if True:                                  # it continues, or overlaps"),
    "nottl": ("[5]", "sni", "            if now - h0[2] < PARTIAL_TTL:\n                break", "            if True:\n                break"),
    "nocap": ("[6]", "sni", "                if len(self._partial) < PARTIAL_MAX and self._partial_src.get(src, 0) < PARTIAL_PER_SRC:",
              "                if True:"),
    "nosrc": ("[6b]", "sni", "                if len(self._partial) < PARTIAL_MAX and self._partial_src.get(src, 0) < PARTIAL_PER_SRC:",
              "                if len(self._partial) < PARTIAL_MAX:"),
    "nowrap": ("[8]", "sni", "                off = (seq - held[0]) & 0xFFFFFFFF", "                off = seq - held[0]"),
    "noretx": ("[9d]", "sni", "                    if off + len(tcp) <= len(buf):\n                        return None",
               "                    if False:\n                        return None"),
    "poll": ("[10]", "sni", "                self._wake.wait(min(IDLE_WAKE, max(0.0, due - mono)))",
             "                self._wake.wait(FLUSH_INTERVAL)"),
    "latechore": ("[12b]", "sni", "                self._wake.wait(min(IDLE_WAKE, max(0.0, due - mono)))",
                  "                self._wake.wait(IDLE_WAKE)"),
    "nowake": ("[11]", "sni", "            if self._pending and (idle or len(self._pending) >= MAX_BATCH):",
               "            if len(self._pending) >= MAX_BATCH:"),
    "nospace": ("[12]", "sni", "or mono - last_write >= FLUSH_INTERVAL):", "or True):"),
    "oldqueue": ("[13]", "noded", Q, '"ct", "packets", "lt", "12",\n            "queue"'),
    "lt5": ("[14]", "noded", Q, '"ct", "original", "packets", "lt", "5",\n            "meta", "length", "gt", "64", "queue"'),
    "noreply": ("[14]", "noded", Q, '"ct", "original", "packets", "lt", "16",\n            "meta", "length", "gt", "52", "queue"'),
    "bytes": ("[14]", "noded", Q, '"ct", "original", "packets", "lt", "16",\n            "ct", "reply", "bytes", "lt", "1000", "meta", "length", "gt", "52", "queue"'),
    "len64": ("[14]", "noded", Q, '"ct", "original", "packets", "lt", "16",\n            "ct", "reply", "avgpkt", "lt", "81", "meta", "length", "gt", "64", "queue"'),
    "norenew": ("[15]", "sni", "                    held[1] = buf; held[2] = now                     # the name is further on: wait for it afresh,\n"
                               "                    self._partial.move_to_end(key)                   # at the back of the table\n",
                "                    held[1] = buf\n"),
    "ttl2": ("[15b]", "sni", "PARTIAL_TTL    = 5.0 ", "PARTIAL_TTL    = 2.0 "),
    "nodrophold": ("[16]", "sni", "        elif self._partial:                            # it names the host by itself",
                   "        elif False:                            # it names the host by itself"),
    "nosweep": ("[17]", "sni", "            if sweep:\n                with self._plock:", "            if False:\n                with self._plock:"),
    "noblkwake": ("[18]", "sni", "                    self._blk_dirty = True             # longer than the next mirror is due in (see _flush_loop)\n"
                                 "                    self._wake.set()\n",
                  "                    self._blk_dirty = True             # longer than the next mirror is due in (see _flush_loop)\n"),
    "blkstays": ("[18]", "sni", "self._blk_last_w = mono; self._blk_dirty = False; blk_snap", "self._blk_last_w = mono; blk_snap"),
    "blknoretry": ("[18]", "sni", "                with self._lock:\n                    self._blk_dirty = True             # not written: again",
                   "                if False:\n                    self._blk_dirty = True             # not written: again"),
    "wallclock": ("[19]", "sni", "            mono = time.monotonic()\n            if n == 0:", "            mono = time.time()\n            if n == 0:"),
    "handqueue": ("[13]", "noded", '_add("ip", "saddr", S, *_sni_queue())',
                  '_add("ip", "saddr", S, "tcp", "dport", "443", "ct", "state", "established", "ct", "packets", "lt", "12", "queue", "num", str(SNI_NFQUEUE), "bypass")'),
}
TMP = tempfile.mkdtemp(prefix="sni-split-")
paths = {"sni": SNI, "noded": NODED}
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _sec, which, old, new = PLANTS[PLANT]
    src = open(paths[which], encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (PLANT, src.count(old))
    paths[which] = os.path.join(TMP, os.path.basename(paths[which]))
    open(paths[which], "w", encoding="utf-8").write(src.replace(old, new, 1))


def load(path, name):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m


S = load(paths["sni"], "swgsni_split")

CHROME = [   # (host, the SNI extension's byte offset, the whole ClientHello record, base64)
  ('one.one.one.one', 1984, (
    "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"
    "ABAADgAMAmgyCGh0dHAvMS4xGhoAAQA=")),
  ('example.com', 1710, (
    "FgMBB84BAAfKAwOo0IAdrRHg7Dkyk3eAVcguppAwShNdC1I55PYkwaP/9SCGuSlq4TDTNvm3rNknaJ5Q/R4nxU+tLiOhuw0u4bcnYwAg6uoTARMC"
    "EwPAK8AvwCzAMMypzKjAE8AUAJwAnQAvADUBAAdhenoAAAArAAcGKioDBAMDABcAAAAQAA4ADAJoMghodHRwLzEuMQASAAAAIwAAADME7wTtqqoA"
    "AQAR7ATAZQM1MiStj+dmewdx4DRulrDGJIbB4Qxc/IYMJwJd7TOKiwHBbVHClMY27kK5/piwDFkSrrCgTdYgt9KiX8RZqfsDq2xDN4QU+Shy+dF1"
    "1vEJ9FNPdhghiGxNNbly++W68gNW6YvCcPo0UDel8EqHeURL6xg1TDkSugEVx1ygegWWRarH+tfHi6SIA4mYNWpgMwyNG9hQ2Tt2DfA0fDtL0pib"
    "pbp5E4WnFivEb4iKYfC7vMeIpOJWzhVmyfWAZPZT/SpTLYAHPgYZUNLPYDwJLNJsHOZJEUSvvVYBCDuht2tLnuadtYVQ2ThNH7A2S0gktlLK5dPJ"
    "WbA5RZURr5x9kXGhzKaDBwxUsFKkHAGV0EkYuvMR+qS3wKScgjWROZmvTtu4fghMt6iMrXq8jfSRuQpi3XHJWWmSauICvFysXEKE1YFnouVjnEm+"
    "LNFHohdHkvZfRxFRDJLLFHgDwTObYDQEk3qPycGWFzWt8vt9F5JvkCRU56Ken9k2Wahphyis4+UU9FR0hpp4elOaPLzDf2BriWYo91NKbExVD6ZI"
    "8ftDmKxxpokOPnsyNfStZWp3gzZaDdAVoDKk5RHN6/YgWPpTZmJlnOsadwqx4td6Vhpw9gRvZtEqyUeIvOlTP3w3x4VrxHc5C8iraseZs3kfqZhl"
    "EDggdhAbOBS5aFYcypYUOrQ6V2sSlJhr5lG5khK3tiQ7AZAYx7cVbsRdZdeq3uazHbi65jZWsmfH7WuvEfdBSeWiL8t7BgRmRnoYRgzFGKV83zlz"
    "ayeA3Oq4GSRnKdCyHzGjD3yV5+QBi/ETNbAY14cNqeaSwpSYlWuAd7SLxtp0xeG2RGae6Qa/8blV6bcB8bUcrTBXOZEkKzWdLmi+yqRXFwdKuIY2"
    "HYwK3ssMjTaTEYglA1xPR4RgRFOa9eHDPLJ74TIuN7h4psgzFWh3+2t87dlx6PNNTErIG8iM+ttuJOhnCzkh20KlO4Wzf5wx5CjB38tgXIFS2DuJ"
    "VthrWnqomQuXY+OC1PQZtSFNWuRjDwI312kBcImCuPWFnqqG/SJ3d6E6G6a8kUEBtSRVH0N98BA21sw9ZKdBJiBjLzsUAsARpSOAL2lQTQO24/W0"
    "cfKaM8HAQxNU4gYJ94GjfrRFUTNDu4Y9uEob/wTBcrVSvpRy8DmgoTN2XMQMYMldPWajULogp8Fu8YsHLDycvms1VCMpQKBuHOQqhnxVD2s9+3Ev"
    "+NdmXxkUF/WJGzswAnk6JKU9G5tR3NFGC0W8FJwsjjQkx3wzAHAw2wmp+FSTExhyR2qn0mIbQbozeZlLxlcDtEMSAlwzSqwHQrq23kgCpLdhflM7"
    "LDas1Lo8KvMdZ/d6rOO6pfCEYHmNgSQgESRTgCmIs5Jc0EC7agRd0dd+z4AwsKdo7WxcgKGh66UVz6xJrLQFY0mI7uFFLthN8SwaxCRJDtCnwimC"
    "VYFLPHoIT4yxV7o5B4GmcPtKD7zFccCVZcNWniyCu9V4GFIfz6ltz2RBu8JVPkU61DU8cqKWCXqgezc1RtRXmBQW5HcXH1/NE/7HeLdq3YWlLS9D"
    "ylfWCBAYyc0JYN77LG3Wo8mKB79Q4A5tXdiqb2gFIlhWcENleayPlCc25j7QZgAdACDx85oD5NBXclkwt1Ue3PFvkGORrAxeOaEBbqcG49QLMgAN"
    "ABoAGHp6CQQJBQkGBAMIBAQBBQMIBQUBCAYGAf4NAPoAAAEAAVsAIA+h7d3Ibvb4W82H/8HJ4i1/LQvFHcekv5hQYZEAXIYAANDsHbpQLOiIa45K"
    "JkMncX3Y751vWiHSnDNvCtTvu46Fz2hU2iDagoNLlM5DrbEhbjFt7cajEMktMm7ybHXRIC+SfMkcpnzePl7NrOqy327CCV4b2lPjM7h/zVy5YTQr"
    "eiaDnMmEduxVkKIDlvMR5crOUcHmKwumMcId004ygeHY8pTZupnt359lkRq2XKPtfnlzz6I1KW2IPvQYYkdKBdkjIpe4X/k+X7+QUSBaqNFFDYD0"
    "/MfWbFB7Z792pYknuquPgGNsfH0ogaekrVNFQjNnAAAAEAAOAAALZXhhbXBsZS5jb20ACgAMAAqqqhHsAB0AFwAYRM0ABQADAmgyyjQAzgDMBYLf"
    "EwIGCIOaZIybLQEIBNZ5CQEE1nkJCAWC3xMCDQTWeQkFBYLfEwIOBNZ5CQsIg5pkjJstAQsE1nkJDAiDmmSMmy0BCgTWeQkDCIOaZIybLQEMBNZ5"
    "CQQE1nkJDwiDmmSMmy0BEwTWeQkHCIOaZIybLQESBNZ5CQoE1nkJAgWC3xMCAQTWeQkOCIOaZIybLQENBNZ5CQkIg5pkjJstAQcFgt8TAhQFgt8T"
    "AhIE1nkJBgWC3xMCDwiDmmSMmy0BCQTWeQkNBYLfEwIT/wEAAQAACwACAQAALQACAQEABQAFAQAAAAAAGwADAgAC6uoAAQA=")),
  ('github.com', 454, (
    "FgMBB80BAAfJAwMbiCZ23wXnsifbx3I2eI28JYMeYZLpV1VnURqVvQM3FyDIs0vawRAy2cSW/w0W5p0uRw9nfkFsecPF2tTEwuOoywAgenoTARMC"
    "EwPAK8AvwCzAMMypzKjAE8AUAJwAnQAvADUBAAdguroAAAAQAA4ADAJoMghodHRwLzEuMQANABoAGJqaCQQJBQkGBAMIBAQBBQMIBQUBCAYGAQAS"
    "AAD+DQD6AAABAAFxACApx+/558FM9we+s+s83tGpXUAeGTFuGTtYUZavnwIyKQDQL9ZLO2qLV72QnomiqBeSlVrM3OCW2P5XEzM5GyH1bfKDuIb6"
    "geiu3yAU7D7XuZ5MElfSXOQpWevoygl7KB2vG7jvwUhfPpq1PYMlw5U5H5QpF0pzs7Gbg31oR9NvCHzcuwwxmXHlJ83WQHhUR6E9nQtyxVZXwAg3"
    "6PcI/DudjhJ1EJxEeBQLfVntHGPvp/L4lV73SPsr+NvA+l5Udh34idEXXD/LKUuKM4upQfqW71teya8U7W9K6+kodKRjOYjhjmYZMggwxQ//83Iw"
    "+YiQakTNAAUAAwJoMgAtAAIBAf8BAAEAAAsAAgEAABcAAAAAAA8ADQAACmdpdGh1Yi5jb20ACgAMAAqamhHsAB0AFwAYAAUABQEAAAAAABsAAwIA"
    "Aso0AM4AzAWC3xMCBgiDmmSMmy0BCATWeQkBBNZ5CQgFgt8TAg0E1nkJBQWC3xMCDgTWeQkLCIOaZIybLQELBNZ5CQwIg5pkjJstAQoE1nkJAwiD"
    "mmSMmy0BDATWeQkEBNZ5CQ8Ig5pkjJstARME1nkJBwiDmmSMmy0BEgTWeQkKBNZ5CQIFgt8TAgEE1nkJDgiDmmSMmy0BDQTWeQkJCIOaZIybLQEH"
    "BYLfEwIUBYLfEwISBNZ5CQYFgt8TAg8Ig5pkjJstAQkE1nkJDQWC3xMCEwAjAAAAMwTvBO2amgABABHsBMA8Qkg/4lOSRBz5MG6rBg04/LxEZ2ww"
    "GaiaoatusKMC0wF9MbS4w5IhN0uczLA+UGcxG4MreQOO4gu+C1RShMvW+skVhVm1kVEkssH9wA8eExy1Fh52ARNascOmPGkhAMgfMZIxkTMdEp/7"
    "yCgiQcjo4nmdukvnqYDi1Gw+NhN2emmTsFmBcpzoF1Duh7T0Mx7YlEBpbK7p6cPxx2022oBkTMWFbHjzsBTkdqS4i1D/YYWZsr2p44PeQzwz7EB6"
    "qMYu+Y0CdlYRsq7PJlyR+8PpBmmx8H9xawya2Vs7E7qo058PAFbZeKtBxa8S3HS0SjV2o0uPuiqi4pC3KlqcxTVA1KH+rG3cczu/EyiNZiQcdxaU"
    "y8Ets0Qw6QZ5IF6AYCOAZUGlV7YRi4ixFFp3uaKlYK9l5Vmsi4iZtz7KV1N7xQUKEwUjBGawCsgrKlDUZCmohSYON8FOlk3kxUeruode83PBJbVX"
    "J0M+OcwAJ2ErCEcImcCnG2XggkB+rFAvZ69Ne8fPqhTTK1akKgzR9E+yFDXItR75QzKc4qw0C2Nux8e85ybBElywRBq/BzhuuDWJN6RyAwXZcQGm"
    "MKLjJ8SXGpjhqWjS2szlq8JnGcMQMXlR5CGRQasQl7CGW3yVY7Whkh95JExCk4l4NLADFjN4JR34yqLjFnxS2RtrS8lhQoVEnB3G1I1EuGRUcHSe"
    "iFOBaWrlER2ggENJur/vbL2CTLeUrKFzxcX3yA8VZAzedzy+M4cVdhC2em7Nojhu8M7Isq/aBK8b+hmB5CInd0LeUinljLglgUHk08semKRWIUwz"
    "NLMcULDAuAEanG0AkzwJelrmcYEJ6RAZUoEu264JQDMpyMQbSmjvlhKMSQfC9ig5c8/8gQUbqoWsBKddWWTkhaimpEEcl5g/7LK/RS5eNRD7aLEM"
    "PHvTo1NWkoON+hWqCZJiqjB25JaAs1HJICfQWquyk3vfFVi2dC1cVXtPx2h0py/EcHjLcWi5J70Tsi+iyhL6Z1+6s5LKIXr1VWQu6o2KIbADWGXK"
    "0G9Cq1FvQmM810NqFbPySLUTqbUqkMrZuJ5UOF7m8kjtxhpP0GepjMhCh8bz4SsBbIIAl4xV0ztSBAEHRQlRGa0hdSb56mkuFFuahlVQSHIb56Kk"
    "hU/0+cU11JxsEGV8M2/+oWmLNAaSdQVqIrwq+JBNwhnZtC5Jc2LQyIbMtnFV4Dse6D+SjJ1ZaK2FB0P8zDmQyyG2857WZWS39LQaFsoqkmP5eWc3"
    "l1aGjFj5+IMJ1CekJFn29s2YbAXAREyfSlQrhbr0awqeFk6NE23no3IOkmH8NRvupL2kHEqJwLA5k2bW7GjSRJ2rgGLnNQU4Z8EOm5GXQoa5WFoA"
    "lbEfdG3gwMW8JaeGQqdbNgZHIjPRNLiBM48++sX4CT9VnFS+MbUpFoPMFHdweqrLOUE89nSL4RiuUsJNgcBRKGfKcoEkuZk0zBieU2fgVho0zFMn"
    "6X3xMD1nmLyz2wXSMyXYEbMW9TVvTEIAQ56JJIA+t3IroA7+sV8mBAOdQ9ckQCyCYTf5Zu070ZQfd8TYjGaWgff1NBuMOeOHVTXdQjP1GnVsSVGJ"
    "ZbJLBPwUOE8R6cNWROg5moA/AB0AIK3fDspJmOpbCfi4sEK8jXyCPJkCwXVADzMb21szAncZACsABwZKSgMEAwMKCgABAA==")),
]

MSS = 1340
DST = "192.0.2.80"


def hello(i):
    host, at, b64 = CHROME[i]
    return host, at, base64.b64decode("".join(b64))


def pkt(payload, seq, sport=40001, dst=DST, src="10.8.0.10"):
    tcp = struct.pack(">HHIIBBHHH", sport, 443, seq & 0xFFFFFFFF, 1, 5 << 4, 0x18, 502, 0, 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0, socket.inet_aton(src), socket.inet_aton(dst))
    return ip + tcp


def segments(data, mss, seq0, sport=40001, dst=DST):
    return [pkt(data[o:o + mss], seq0 + o, sport, dst) for o in range(0, len(data), mss)]


class CountingEvent(threading.Event):
    def __init__(self):
        super().__init__(); self.waits = 0

    def wait(self, timeout=None):
        self.waits += 1
        return super().wait(timeout)


def classifier(hosts, flusher=False, cat="web"):
    """A Classifier over a map naming `hosts` (in `cat`), with nft stubbed — the real loop started only when `flusher`."""
    d = os.path.join(tempfile.mkdtemp(prefix="sni-map-"), "sni-map.json")
    open(d, "w").write('{"%s": %s}' % (cat, str(list(hosts)).replace("'", '"')))
    C = S.Classifier.__new__(S.Classifier)
    C.map_path, C.table, C.reset_mark, C.learn_ttl, C.refresh_age = d, "swg_smart", 0x9999, 3600, 1800
    C.map_mtime = C.pat_mtime = None; C.dom2cat = {}; C.pats = S._empty_pats()
    C.pat_path = os.path.join(os.path.dirname(d), "sni-patterns.json"); C.blk_path = os.path.join(os.path.dirname(d), "blk.json")
    C._blk_hits, C._blk_last_w, C._blk_dirty, C.seen, C._pending = {}, 0.0, False, {}, []
    C._lock, C._wake, C._partial, C._partial_src = threading.Lock(), CountingEvent(), collections.OrderedDict(), {}   # as __init__ sets them
    C._plock = threading.Lock()
    C._last_reload, C._last_prune = time.time(), time.monotonic()
    C._reload()
    C.writes = []
    C._write_learned = lambda batch: C.writes.append((time.monotonic(), list(batch)))
    if flusher:
        threading.Thread(target=C._flush_loop, name="flush", daemon=True).start()
    return C


try:
    # ── THE HELLO ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("[1] the fixtures")
    for i in range(3):
        host, at, ch = hello(i)
        one = S.parse_sni(ch[:MSS]); whole = S.parse_sni(ch)
        want_one = host if at + 9 + len(host) <= MSS else None
        check("[1] %s (%d B, SNI at %d): the whole parses to it; a one-segment parse of %d B finds %s"
              % (host, len(ch), at, MSS, want_one or "nothing"), whole == host and one == want_one, (whole, one))

    print("\n[2] the name in the 2nd segment")
    for i in (0, 1):
        host, at, ch = hello(i)
        C = classifier([host])
        s1, s2 = segments(ch, MSS, 1000)
        v1 = C.on_packet(s1)
        mid = list(C._pending)
        v2 = C.on_packet(s2)
        check("[2] %s: the 1st segment teaches nothing and is not reset" % host, v1 is None and not mid, (v1, mid))
        check("[2] %s: the 2nd completes it — the address queued for its category, the reset on the 2nd" % host,
              v2 == 0x9999 and C._pending == [("web", DST)] and not C._partial, (v2, C._pending, len(C._partial)))

    print("\n[3] the name in the 1st segment")
    host, at, ch = hello(2)
    C = classifier([host])
    s1, s2 = segments(ch, MSS, 5000)
    v1 = C.on_packet(s1); after1 = list(C._pending)
    v2 = C.on_packet(s2)
    check("[3] learned and reset on the 1st, nothing more on the 2nd, nothing left held",
          v1 == 0x9999 and after1 == [("web", DST)] and v2 is None and C._pending == after1 and not C._partial,
          (v1, after1, v2, C._pending, len(C._partial)))

    print("\n[4]–[5] only the exact continuation, in time")
    host, at, ch = hello(0)
    C = classifier([host]); s1, s2 = segments(ch, MSS, 9000)
    C.on_packet(s1)
    bad = pkt(ch[MSS:], 9000 + MSS + 7)
    check("[4] a segment that leaves a gap is not joined", C.on_packet(bad) is None and not C._pending, C._pending)
    check("[4] …and the hello is kept: the segment that does fit still completes it", C.on_packet(s2) == 0x9999
          and C._pending == [("web", DST)], C._pending)
    C = classifier([host]); C.on_packet(s1)
    if C._partial:                                      # age what the 1st segment left held past PARTIAL_TTL
        k = next(iter(C._partial)); C._partial[k][2] -= S.PARTIAL_TTL + 1
        check("[5] one arriving after PARTIAL_TTL is not joined", C.on_packet(s2) is None and not C._pending, C._pending)
    else:
        check("[5] one arriving after PARTIAL_TTL is not joined — the 1st segment was not even held", False, "nothing held")

    print("\n[6] held hellos are bounded")
    C = classifier([host])
    for n in range(S.PARTIAL_MAX + 50):                   # from many clients (one alone is capped at PARTIAL_PER_SRC)
        C.on_packet(pkt(ch[:MSS], 7, sport=1024 + n, src="10.9.%d.%d" % (n // 250, n % 250 + 1)))
    full = len(C._partial)
    for k in list(C._partial)[:10]:
        C._partial[k][2] -= S.PARTIAL_TTL + 1
    C.on_packet(pkt(ch[:MSS], 7, sport=60000, src="10.10.0.1"))
    check("[6] at most PARTIAL_MAX held, and the timed-out ones make room for a new one",
          full == S.PARTIAL_MAX and len(C._partial) <= S.PARTIAL_MAX and any(k[1][:2] == struct.pack(">H", 60000) for k in C._partial),
          (full, len(C._partial)))

    C = classifier([host])
    for n in range(S.PARTIAL_PER_SRC + 5):
        C.on_packet(pkt(ch[:MSS], 7, sport=20000 + n))
    one = len(C._partial)
    tcp2 = struct.pack(">HHIIBBHHH", 30000, 443, 7, 1, 5 << 4, 0x18, 502, 0, 0) + ch[:MSS]
    ip2 = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp2), 0, 0, 64, 6, 0, socket.inet_aton("10.8.0.99"), socket.inet_aton(DST))
    C.on_packet(ip2 + tcp2)
    check("[6b] one client holds at most PARTIAL_PER_SRC (%d), and another client still gets a slot" % S.PARTIAL_PER_SRC,
          one == S.PARTIAL_PER_SRC and len(C._partial) == S.PARTIAL_PER_SRC + 1, (one, len(C._partial)))

    print("\n[7]–[9]")
    host, at, ch = hello(0)
    C = classifier([host]); parts = segments(ch, 700, 100)
    vs = [C.on_packet(p) for p in parts]
    check("[7] three segments (MSS 700): learned on the 3rd, nothing before", len(parts) == 3 and vs[:2] == [None, None]
          and vs[2] == 0x9999 and C._pending == [("web", DST)], (len(parts), vs, C._pending))
    C = classifier([host]); s1, s2 = segments(ch, MSS, 2 ** 32 - 300)
    C.on_packet(s1)
    check("[8] a sequence number wrapping at 2^32 still joins", C.on_packet(s2) == 0x9999 and C._pending == [("web", DST)], C._pending)
    C = classifier([host])
    appdata = b"\x17\x03\x03\x40\x00" + b"x" * 1300
    C.on_packet(pkt(appdata, 1)); C.on_packet(pkt(b"\x16\x03\x01\x00\x20\x02" + b"y" * 40, 1, sport=40002))
    check("[9] data that is not a ClientHello (app data, a ServerHello) is never held", not C._partial, len(C._partial))
    C = classifier([host]); s1, s2 = segments(ch, MSS, 3000)
    vs = [C.on_packet(p) for p in (s1, s1, s2)]
    check("[9b] a retransmitted 1st segment between the two: still joins", vs == [None, None, 0x9999] and C._pending == [("web", DST)],
          (vs, C._pending))
    C = classifier([host])
    vs = [C.on_packet(pkt(ch[:MSS], 3000)), C.on_packet(pkt(ch[MSS - 100:], 3000 + MSS - 100))]
    check("[9c] a re-cut 2nd segment overlapping the 1st by 100 bytes: joins", vs == [None, 0x9999], vs)
    C = classifier([host]); parts = segments(ch, 700, 4000)
    vs = [C.on_packet(p) for p in (parts[0], parts[1], parts[0], parts[2])]
    check("[9d] three segments, the 1st retransmitted after the 2nd: nothing held is cut, the 3rd completes it",
          vs == [None, None, None, 0x9999], vs)

    # ── THE FLUSHER ────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[10]–[12] the flusher (its real loop)")
    host, at, ch = hello(2)
    C = classifier([host], flusher=True)
    time.sleep(0.6)
    idle_waits = C._wake.waits
    check("[10] idle for 0.6 s, it waited %d time(s) — no polling (it used to wake every %d ms)"
          % (idle_waits, S.FLUSH_INTERVAL * 1000), idle_waits <= 2, idle_waits)
    t0 = time.monotonic()
    C.on_packet(pkt(ch, 1))
    for _ in range(200):
        if C.writes:
            break
        time.sleep(0.002)
    lat = (C.writes[0][0] - t0) * 1000 if C.writes else None
    check("[11] the first learn after a quiet spell is written at once (%s ms)" % (round(lat, 1) if lat is not None else "never"),
          lat is not None and lat < 100, lat)
    C.writes.clear()
    for n in range(20):                                  # 20 new destinations, 3 ms apart — a stream of first sights
        C.on_packet(pkt(ch, 1, sport=41000 + n, dst="198.51.100.%d" % (n + 1)))
        time.sleep(0.003)
    time.sleep(0.1)
    gaps = [(b[0] - a[0]) * 1000 for a, b in zip(C.writes, C.writes[1:])]
    written = sum(len(w[1]) for w in C.writes)
    check("[12] a stream of 20 learns: all written, in %d writes, each at least ~FLUSH_INTERVAL apart (%s ms)"
          % (len(C.writes), [round(g) for g in gaps]),
          written == 20 and len(C.writes) < 20 and all(g >= S.FLUSH_INTERVAL * 1000 * 0.8 for g in gaps), (written, gaps))
    C = classifier([host], flusher=False)
    mirrored = []
    C._write_blk = lambda hits: mirrored.append(time.monotonic()) or True
    C._blk_hits, C._blk_dirty = {"blocked.example": 3}, True
    C._blk_last_w = time.monotonic() - S.BLK_WRITE_EVERY + 0.3                        # due in 0.3 s
    t0 = time.monotonic(); threading.Thread(target=C._flush_loop, daemon=True).start()
    for _ in range(300):
        if mirrored:
            break
        time.sleep(0.01)
    late = (mirrored[0] - t0) if mirrored else None
    check("[12b] idle, the blocked-hits mirror due in 0.3 s is written then (%s s), not up to IDLE_WAKE (%g s) late"
          % (round(late, 2) if late is not None else "not within 3", S.IDLE_WAKE), late is not None and late < 1.5, late)

    # ── THE QUEUE ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("\n[13]–[14] the queue")
    src = open(paths["noded"], encoding="utf-8").read()
    N = load(paths["noded"], "swgnoded_split")
    q = list(N._sni_queue())
    check("[13] one match hands swg-sni its packets: `queue num` is written once, in _sni_queue, and used by all four rules",
          src.count('"queue", "num"') == 1 and src.count("*_sni_queue()") == 4, (src.count('"queue", "num"'), src.count("*_sni_queue()")))
    check("[13] …and it is the ClientHello's: data, before the server has answered, within the client's first 15",
          " ".join(q).startswith("tcp dport 443 ct state established ct original packets lt 16 ct reply avgpkt lt 81 "
                                 "meta length gt 52 queue num")
          and "ct packets" not in " ".join(q), " ".join(q))
    check("[13] a node whose engine is swg-sni re-signs its smart chain once (`q2`); no other mode's signature moves",
          '("q2;" if queue else "")' in src and '("q;" if queue else "")' not in src, "")
    sys.path.insert(0, HERE)
    from nft_guarded_model import SmartModel
    M = SmartModel()
    M.script("add table inet t\nadd chain inet t prerouting { type filter hook prerouting priority mangle; policy accept; }\n"
             "add rule inet t prerouting ip saddr 10.8.0.0/24 " + " ".join(q))
    kw = dict(ct="established", ctpackets=6)
    v = {name: M.packet("t", "wg0", "10.8.0.10", DST, ctorig=co, length=ln, replybytes=rb, replypkts=rp, **kw)["verdict"]
         for name, co, ln, rb, rp in (   # (the client's packets so far, this one's length, the server's bytes, its packets)
             ("ack", 2, 52, 60, 1), ("ack_nots", 2, 40, 52, 1),                     # the handshake's ACK, after the SYN-ACK
             ("ch1", 3, 1392, 60, 1), ("ch2", 4, 723, 112, 2),                      # a hello in two, the server ACKing the 1st
             ("ch1_retx_5th", 5, 1392, 164, 3), ("ch3_7th", 7, 600, 216, 4),
             ("tail", 4, 57, 112, 2),                                               # a 5-byte tail (timestamps: 52 + 5)
             ("after_sacks", 5, 1392, 220, 3),                                      # the 1st again, after two 80-byte SACKs
             ("finished", 5, 150, 3500, 4),                                         # after a full handshake's flight
             ("resumed_finished", 5, 126, 464, 3), ("resumed_request", 6, 452, 516, 4),   # after a 300-byte resumed one
             ("sixteenth", 16, 600, 300, 5))}
    check("[14] a bare ACK (52 B, or 40 without timestamps) is not queued", v["ack"] == v["ack_nots"] == "accept", v)
    check("[14] the ClientHello's segments are — the 1st retransmitted as the client's 5th packet, a 3rd as its 7th, a "
          "5-byte tail, the 1st again after the server's SACKs",
          v["ch1"] == v["ch2"] == v["ch1_retx_5th"] == v["ch3_7th"] == v["tail"] == v["after_sacks"] == "queue", v)
    check("[14] nothing once the server has sent its flight — a full handshake's, a resumed one's (its Finished, its "
          "request) — and nothing past the client's 15th packet",
          v["finished"] == v["resumed_finished"] == v["resumed_request"] == v["sixteenth"] == "accept", v)

    # ── FROM THE REVIEW OF THE FIXES ───────────────────────────────────────────────────────────────────────────────────────
    def age(C, secs):
        for h in C._partial.values():
            h[2] -= secs
    print("\n[15] a held hello waits PARTIAL_TTL for its NEXT segment")
    host, at, ch = hello(0)
    C = classifier([host]); parts = segments(ch, 700, 6000)
    C.on_packet(parts[0]); age(C, S.PARTIAL_TTL - 1)
    v2 = C.on_packet(parts[1]); age(C, S.PARTIAL_TTL - 1)
    v3 = C.on_packet(parts[2])
    check("[15] three segments, each PARTIAL_TTL − 1 s after the last (%g s in all): learned on the 3rd — an addition "
          "renews the wait" % (2 * (S.PARTIAL_TTL - 1)), v2 is None and v3 == 0x9999 and C._pending == [("web", DST)],
          (v2, v3, C._pending))
    C = classifier([host])
    a1, a2 = segments(ch, 700, 100, sport=41001)[:2]
    C.on_packet(a1); C.on_packet(segments(ch, 700, 100, sport=41002)[0]); C.on_packet(a2)
    keys = list(C._partial)
    check("[15] …and moves its hello to the back of the table, which stays oldest first",
          len(keys) == 2 and keys[-1][1][:2] == struct.pack(">H", 41001), [k[1][:2] for k in keys])
    C = classifier([host]); s1, s2 = segments(ch, MSS, 7000)
    C.on_packet(s1); age(C, 3.0)
    check("[15b] a 2nd segment 3 s after the 1st (a retransmit after a loss, on a slow path) still joins",
          C.on_packet(s2) == 0x9999 and C._pending == [("web", DST)], C._pending)

    print("\n[16] a segment that names its host by itself")
    C = classifier([host])
    C.on_packet(pkt(ch[:MSS], 8000)); held = len(C._partial)
    v = C.on_packet(pkt(ch, 8000))                        # the same flow: the whole hello in one (a retransmit re-cut to carry it)
    check("[16] …ends the hello held for its flow: learned, nothing left held, its client's slot free again",
          held == 1 and v == 0x9999 and not C._partial and not C._partial_src, (held, v, len(C._partial), C._partial_src))

    print("\n[17] the held hellos, when no packet comes")
    C = classifier([host])
    for n in range(5):
        C.on_packet(pkt(ch[:MSS], 9, sport=42000 + n))
    before = len(C._partial); age(C, S.PARTIAL_TTL + 1)
    C._last_prune = time.monotonic() - S.PRUNE_EVERY    # its prune is due
    threading.Thread(target=C._flush_loop, daemon=True).start()
    for _ in range(100):
        if not C._partial:
            break
        time.sleep(0.01)
    check("[17] 5 held, timed out, no traffic: the flusher's prune drops them, and their client's count",
          before == 5 and not C._partial and not C._partial_src, (before, len(C._partial), C._partial_src))

    print("\n[18] the blocked-hits mirror")
    h2, _, ch2 = hello(2)
    saved = (S.BLK_WRITE_EVERY, S.IDLE_WAKE)
    S.BLK_WRITE_EVERY, S.IDLE_WAKE = 0.3, 30.0          # the flusher asleep until its prune, 30 s off
    try:
        C = classifier([h2], cat="blku_x")
        mirrored = []
        C._write_blk = lambda hits: mirrored.append((time.monotonic(), dict(hits))) or True
        threading.Thread(target=C._flush_loop, daemon=True).start()
        time.sleep(0.1)
        C.on_packet(pkt(ch2, 1, sport=43000))           # first sight: a learn (which wakes it) and a blocked hit
        time.sleep(0.6)                                  # past BLK_WRITE_EVERY
        n1 = len(mirrored); t0 = time.monotonic()
        C.on_packet(pkt(ch2, 1, sport=43001))           # the same address again: nothing to learn — only the hit
        for _ in range(100):
            if len(mirrored) > n1:
                break
            time.sleep(0.01)
        late = mirrored[n1][0] - t0 if len(mirrored) > n1 else None
        check("[18] a hit with nothing to learn wakes the flusher, and its mirror goes out at once (%s s)"
              % (round(late, 2) if late is not None else "not within 1"), n1 == 1 and late is not None and late < 0.2
              and mirrored[-1][1] == {h2: 2}, (n1, late, mirrored[-1][1] if mirrored else None))
        n2 = len(mirrored); time.sleep(1.0)
        check("[18] …and with no hit since, it is not rewritten (%d more in 1 s, BLK_WRITE_EVERY %g s)"
              % (len(mirrored) - n2, S.BLK_WRITE_EVERY), len(mirrored) == n2, len(mirrored) - n2)
        C = classifier([h2], cat="blku_x")
        tries = []
        C._write_blk = lambda hits: tries.append(time.monotonic()) and False   # a full disk: never written
        threading.Thread(target=C._flush_loop, daemon=True).start()
        C.on_packet(pkt(ch2, 1, sport=43100)); time.sleep(0.8)
        check("[18] one that could not be written is tried again when the next is due (%d tries in 0.8 s)" % len(tries),
              len(tries) >= 2, len(tries))
    finally:
        S.BLK_WRITE_EVERY, S.IDLE_WAKE = saved

    print("\n[19] idle, the flusher's own clock")
    saved = (S.PRUNE_EVERY, S.IDLE_WAKE)
    S.PRUNE_EVERY, S.IDLE_WAKE = 0.2, 30.0
    try:
        C = classifier([h2], flusher=True)
        time.sleep(1.05)
        w = C._wake.waits
        check("[19] a prune every 0.2 s, idle 1.05 s: %d waits — one per prune and the first, none between" % w, 4 <= w <= 8, w)
    finally:
        S.PRUNE_EVERY, S.IDLE_WAKE = saved
finally:
    pass

if PLANT:
    marker = PLANTS[PLANT][0]
    hit = [f for f in FAILS if f.startswith(marker)]
    print("\nPLANT %s: %s" % (PLANT, "CAUGHT — " + " · ".join(hit) if hit else "NOT CAUGHT (the check passed with the defect in)"))
    sys.exit(0 if hit else 1)
print("\n" + ("All checks passed." if not FAILS else "FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
