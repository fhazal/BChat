"""Runs the built BChat.exe with a temp settings folder against the local fake server over SSL, and clicks its real window.

    python tools/qa/frozen_check.py [--exe dist/BChat/BChat.exe] [--out DIR]
"""
import ctypes, ctypes.wintypes as wt, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from PIL import Image

from qa_common import ROOT, finish, parse_args, self_signed_cert
sys.path.insert(0, str(ROOT / "tests"))
from fake_ircd import FakeIrcd

ARGS = parse_args("Packaged app: start, TLS to a local fake server, real window, menus and buttons.")
OUT = ARGS.out
EXE = ARGS.exe
u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
u.SetProcessDPIAware()
tmp = Path(tempfile.mkdtemp())
crt, key = self_signed_cert(tmp)   # throwaway certificate (made with Git's openssl.exe before 11-11-2026)
srv = FakeIrcd(crt, key)
cfgdir = tmp / "cfg"; cfgdir.mkdir()
(cfgdir / "config.json").write_text(json.dumps({"nick": "Badaboom", "imported": True, "skip_network_list": True, "networks": [
    {"name": "SkinIRC", "servers": [{"host": "127.0.0.1", "port": srv.port, "ssl": True}], "autojoin": "#skinhead",
     "autoconnect": True, "allow_invalid_cert": True}]}))
p = subprocess.Popen([EXE, "--config-dir", str(cfgdir)], env=dict(os.environ, BCHAT_VAULT="file"))   # throwaway settings: stand-in vault
WNDENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


def windows():
    res = []
    def cb(h, _):
        pid = wt.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == p.pid and u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(200); u.GetWindowTextW(h, b, 200)
            r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
            res.append((h, b.value, r.right - r.left, r.bottom - r.top))
        return True
    u.EnumWindows(WNDENUM(cb), 0)
    return res


def shot(h, w, ht, name):
    wdc = u.GetWindowDC(h); dc = g.CreateCompatibleDC(wdc); bm = g.CreateCompatibleBitmap(wdc, w, ht)
    g.SelectObject(dc, bm); u.PrintWindow(h, dc, 2)
    class BI(ctypes.Structure):
        _fields_ = [("s", wt.DWORD), ("w", wt.LONG), ("h", wt.LONG), ("p", wt.WORD), ("b", wt.WORD), ("c", wt.DWORD), ("i", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("u", wt.DWORD), ("n", wt.DWORD)]
    bi = BI(ctypes.sizeof(BI), w, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * ht * 4); g.GetDIBits(dc, bm, 0, ht, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGBA", (w, ht), buf, "raw", "BGRA", 0, 1).convert("RGB").save(OUT / name)
    g.DeleteObject(bm); g.DeleteDC(dc); u.ReleaseDC(h, wdc)


def click(h, x, y):
    lp = (y << 16) | x
    u.PostMessageW(h, 0x200, 0, lp); time.sleep(0.05)
    u.PostMessageW(h, 0x201, 1, lp); time.sleep(0.05)
    u.PostMessageW(h, 0x202, 0, lp); time.sleep(0.4)


def wait(cond, sec=15):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


results = {}
try:
    results["window opened"] = wait(lambda: any(w[1].startswith("BChat") for w in windows()))
    results["logged in over SSL"] = wait(lambda: any(x.startswith("USER") for x in srv.received))
    results["joined channel"] = wait(lambda: "JOIN #skinhead" in srv.received)
    time.sleep(1.5)
    srv.send(":Belon!b@h PRIVMSG #skinhead :hello from the test server")
    time.sleep(0.5)
    main = next(w for w in windows() if w[1].startswith("BChat"))
    h, _, W, H = main
    print("title:", main[1], "size", W, H)
    shot(h, W, H, "main.png")
    scale = ctypes.WinDLL("user32").GetDpiForWindow(h) / 96
    print("scale", scale)
    s = lambda v: int(v * scale)
    WL = W / scale
    RED, GREEN, YELLOW = int(WL - 16), int(WL - 36), int(WL - 56)
    def strip():
        shot(h, W, H, "_strip.png")
        im = Image.open(OUT / "_strip.png").convert("RGB")
        y = H - s(14)
        for x in range(W - 1, W - s(14), -1):
            r, gg, b = im.getpixel((x, y))
            if max(r, gg, b) > 140:
                return "#%02x%02x%02x" % (r, gg, b)
        return None
    results["strip green when connected"] = strip() == "#a6e3a1"
    print("strip:", strip())
    srv.send(":Fhazal!f@h MODE #skinhead +o Badaboom")
    time.sleep(1.5)
    results["strip blue when op"] = strip() == "#74c7ec"
    shot(h, W, H, "op.png")
    srv.send(":Fhazal!f@h MODE #skinhead -o Badaboom")
    time.sleep(1.5)
    results["strip back to green"] = strip() == "#a6e3a1"
    # green: maximise and back
    click(h, s(GREEN), s(14))
    results["green maximizes"] = wait(lambda: bool(u.IsZoomed(h)), 3)
    u_r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(u_r))
    click(h, u_r.right - u_r.left - s(36), s(14))
    results["green restores"] = wait(lambda: not u.IsZoomed(h), 3)
    # yellow: minimise, then bring back
    click(h, s(YELLOW), s(14))
    results["yellow minimizes"] = wait(lambda: bool(u.IsIconic(h)), 3)
    u.ShowWindow(h, 9)
    print("after buttons: QUIT at server =", any(x.startswith("QUIT") for x in srv.received))
    wait(lambda: not u.IsIconic(h), 3)
    time.sleep(0.5)
    # menu bar: each of the six menus opens a popup
    before = {w[0] for w in windows()}
    names = ["BChat", "View", "Server", "Settings", "Window", "Help"]
    xs = [20, 75, 118, 170, 225, 265]
    for name, x in zip(names, xs):
        click(h, s(x), s(38))
        pops = [w for w in windows() if w[0] not in before]
        if not pops:
            time.sleep(0.5)
            click(h, s(x), s(38))
            pops = [w for w in windows() if w[0] not in before]
        results[f"menu {name} opens"] = bool(pops)
        print(f"after menu {name}: QUIT at server =", any(x.startswith("QUIT") for x in srv.received))
        if pops:
            shot(pops[0][0], pops[0][2], pops[0][3], f"menu-{name}.png")
        u.PostMessageW(h, 0x100, 0x1B, 0); u.PostMessageW(h, 0x101, 0x1B, 0)
        if pops:
            u.PostMessageW(pops[0][0], 0x100, 0x1B, 0); u.PostMessageW(pops[0][0], 0x101, 0x1B, 0)
        time.sleep(0.4)
    # /server from the built program: moves to a second local server
    other = FakeIrcd()
    # close anything still open, then click the input box like a person would
    for _ in range(3):
        for w in windows():
            u.PostMessageW(w[0], 0x100, 0x1B, 1); u.PostMessageW(w[0], 0x101, 0x1B, 0xC0000001)
        time.sleep(0.3)
    print("open popups before typing:", [w[1] or "(popup)" for w in windows() if w[0] != h])
    click(h, W // 2, H - s(11))
    shot(h, W, H, "before-typing.png")
    print("checkpoint before typing: QUIT at server =", any(x.startswith("QUIT") for x in srv.received), "| lines:", [x[:40] for x in srv.received[-3:]])
    VK = {"/": 0xBF, " ": 0x20, ".": 0xBE}
    for ch in f"/server 127.0.0.1 {other.port}":
        vk = VK.get(ch) or ord(ch.upper())
        u.PostMessageW(h, 0x100, vk, 1); u.PostMessageW(h, 0x101, vk, 0xC0000001); time.sleep(0.02)
    u.PostMessageW(h, 0x100, 0x0D, 1); u.PostMessageW(h, 0x101, 0x0D, 0xC0000001)
    results["/server moves to the new server"] = wait(lambda: "NICK Badaboom" in other.received, 8)
    results["/server sent nothing odd to the old one"] = not any(x.upper().startswith("SERVER") for x in srv.received)
    time.sleep(1)
    shot(h, W, H, "after-server.png")
    # red: asks before dropping a live connection
    click(h, s(RED), s(14))
    time.sleep(0.8)
    box = [w for w in windows() if w[0] != h]
    results["red asks before quit"] = bool(box) and any("Quit" in w[1] for w in box)
    if box:
        shot(box[0][0], box[0][2], box[0][3], "quit-prompt.png")
finally:
    alive = p.poll() is None
    results["still running at the end"] = alive
    p.kill()
    srv.stop()
finish("frozen_check", ARGS, results)
