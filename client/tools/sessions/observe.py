"""Observe: scene creation, HTTP requests, crashes, and pending preload requests."""
SCENES = {
    0x140144530: "Briefing", 0x140146ec0: "Closed", 0x140147e40: "ErrorPopup", 0x140148340: "MakerLogo",
    0x14014bb90: "StaffRoll", 0x14015ce10: "SequenceBase", 0x140161590: "SequenceCommunity",
    0x1401618e0: "SequenceCustomize", 0x1401625a0: "SequenceGallery", 0x140162880: "SequenceNews",
    0x140162bf0: "SequencePlay", 0x1401632d0: "SequenceRecord", 0x1401635d0: "SequenceStore",
    0x140164250: "SteamTest", 0x1401653a0: "WindowTest", 0x1401dab60: "Battle", 0x1401e4630: "BootScreen",
    0x1401e5fd0: "Initial", 0x1401e60e0: "Initial::VSBotFlow", 0x1401e72d0: "InitialBattle",
    0x1401e77a0: "InitialGame", 0x1401e7b90: "NetworkInitialize", 0x1401eca40: "OtherSelect",
    0x1401ecc70: "Select", 0x1401ece80: "Title",
}


def pending(d):
    """Unfinished requests in the six persistent preloaders (layout from Codex's InspectBackup.cs)."""
    out = []
    for i in range(6):
        q = d.q(0x141B941F0 + 8 * i)
        if not q:
            continue
        lst = d.q(q + 0x40)
        begin, end = d.q(lst + 8), d.q(lst + 16)
        n = (end - begin) // 0x138 if end > begin else 0
        waiting = []
        for k in range(min(n, 4000)):
            e = begin + k * 0x138
            if d.d32(e + 0x110) == 0:
                res = d.q(e + 0x108)
                state = d.d32(res + 0xB0) if res else None
                waiting.append(f"{d.cstr(e, 256)!r} res={res:x} state={state}")
        out.append((i, n, waiting))
    return out


def setup(d):
    for addr, name in SCENES.items():
        d.bp(addr, lambda h, n=name: d.log(f"SCENE create {n} (from {h.ret():x})"))

    def open_request(h):
        d.log(f"HTTP OpenRequest {h.wstr(h.rdx)} {h.wstr(h.r8)}")

    def send_request(h):
        body, n = h.q(h.rsp + 0x20), h.d(h.rsp + 0x28)
        hdr = h.wstr(h.rdx, 1024) if h.rdx else ""
        d.log(f"HTTP Send headers={hdr!r} body[{n}]={h.read(body, min(n, 2000))!r}")

    d.bp(0x140B3BAB4, open_request)
    d.bp(0x140B3BC15, send_request)

    last = {}

    def poll(dd):
        for i, n, waiting in pending(dd):
            key = (i, n, tuple(waiting[:10]))
            if last.get(i) != key:
                last[i] = key
                dd.log(f"preloader {i}: {n} entries, {len(waiting)} pending " + "; ".join(waiting[:10]))

    d.poll(poll, 10.0)
