from pathlib import Path

from bchat.config import Config, NetworkConfig, load, save
from bchat.protocol import build_line, lower, mask_ban, parse_format, parse_line, split_urls, strip_format
from bchat.xchat_import import import_into, parse_server, parse_servlist


def test_parse_full_line():
    m = parse_line("@time=2026-11-07T01:02:03.000Z :nick!u@h PRIVMSG #c :hello there")
    assert (m.command, m.nick, m.userhost, m.params) == ("PRIVMSG", "nick", "u@h", ["#c", "hello there"])
    assert m.tags["time"].startswith("2026")


def test_parse_no_trailing_and_colon_in_middle():
    assert parse_line(":s 005 me A=1 B=2 :ok").params == ["me", "A=1", "B=2", "ok"]
    assert parse_line("PING :abc").params == ["abc"]
    assert parse_line("MODE #c +o a:b").params == ["#c", "+o", "a:b"]


def test_build_line():
    assert build_line("PRIVMSG", "#c", "hi there") == "PRIVMSG #c :hi there"
    assert build_line("NICK", "me") == "NICK me"
    assert build_line("PRIVMSG", "#c", ":)") == "PRIVMSG #c ::)"
    assert build_line("TOPIC", "#c", "") == "TOPIC #c :"


def test_rfc_lower():
    assert lower("B3L0N[JVN]") == lower("b3l0n{jvn}")


def test_format_spans():
    s = parse_format("a\x02b\x02\x034,5c\x03d\x0fe")
    assert [x.text for x in s] == ["a", "b", "c", "d", "e"]
    assert s[1].bold and not s[2].bold
    assert (s[2].fg, s[2].bg) == (4, 5)
    assert s[3].fg is None
    assert strip_format("\x0304red\x03") == "red"


def test_urls_leave_punctuation_out():
    assert split_urls("see https://a.my/x, ok") == [("see ", False), ("https://a.my/x", True), (", ok", False)]


def test_ban_masks():
    assert mask_ban("n", "~root@a.b.my", 0) == "*!*@*.b.my"
    assert mask_ban("n", "~root@a.b.my", 1) == "*!*@a.b.my"
    assert mask_ban("n", "~root@a.b.my", 2) == "*!*root@*.b.my"
    assert mask_ban("n", "~root@a.b.my", 3) == "*!*root@a.b.my"
    assert mask_ban("n", "u@1.2.3.4", 0) == "*!*@1.2.3.*"
    assert mask_ban("n", "", 0) == "n!*@*"


def test_server_entry():
    s = parse_server("znc.skinhead.com.my/+5599", False)
    assert (s.host, s.port, s.ssl) == ("znc.skinhead.com.my", 5599, True)
    assert parse_server("irc.x.org", False).port == 6667
    assert parse_server("irc.x.org", True).port == 6697


def test_servlist_flags():
    nets = parse_servlist("v=1\n\nN=SkinIRC\nU=me/net\nP=secret\nF=45\nD=0\nS=znc.a.my/+5599\n\nN=Old\nF=22\nS=irc.x\n".splitlines())
    a, b = nets
    assert a.autoconnect and a.cycle and a.allow_invalid_cert and not a.use_global
    assert a.password == "secret" and a.username == "me/net" and a.servers[0].ssl
    assert not b.autoconnect and b.use_global and b.servers[0].ssl  # F=22 has the SSL bit


def test_import_merges_and_report_has_no_secrets(tmp_path: Path):
    src = tmp_path / "XChat-SE"
    src.mkdir()
    (src / "servlist.conf").write_text("N=SkinIRC\nU=me\nP=hunter2\nF=45\nS=znc.a.my/+5599\n\nN=Stock\nF=22\nS=irc.x\n")
    (src / "xchat.conf").write_text("irc_nick1 = Badaboom\nirc_nick2 = b2\nirc_quit_reason = bye\n")
    (src / "colors.conf").write_text("color_0 = ffff 0000 0000\ncolor_259 = 0000 0000 0000\n")
    cfg = Config()
    report = import_into(cfg, [src], colors=True)
    assert cfg.nick == "Badaboom" and cfg.quit_reason == "bye"
    assert [n.name for n in cfg.networks] == ["SkinIRC", "Stock"]
    assert cfg.theme.palette[0] == "#ff0000" and cfg.theme.chat_bg == "#000000"
    assert "hunter2" not in " ".join(report)


def test_light_colours_are_not_imported(tmp_path: Path):
    src = tmp_path / "X-Chat 2"
    src.mkdir()
    (src / "colors.conf").write_text("color_0 = 0000 0000 0000\ncolor_258 = 0000 0000 0000\ncolor_259 = ffff ffff ffff\n")
    cfg = Config()
    before = cfg.theme.chat_bg
    report = import_into(cfg, [src], colors=True)
    assert cfg.theme.chat_bg == before and cfg.theme.palette[0] != "#000000"
    assert "skipped" in report[0]


def test_config_roundtrip(tmp_path: Path):
    cfg = Config(nick="x", networks=[NetworkConfig("N", password="p")])
    save(cfg, tmp_path)
    back = load(tmp_path)
    assert back.nick == "x" and back.networks[0].password == "p"
    assert back.theme.window == cfg.theme.window


def test_broken_config_is_kept_aside(tmp_path: Path):
    (tmp_path / "config.json").write_text("{not json")
    assert load(tmp_path).nick.startswith("Bee")       # starts fresh, as on a first start
    assert (tmp_path / "config.broken.json").exists()


def test_icon_levels_follow_xchat():
    from bchat.userlist import icon_name
    assert icon_name("@%+", "@") == "op"
    assert icon_name("@%+", "%") == "hop"
    assert icon_name("@%+", "+") == "voice"
    assert icon_name("~&@%+", "&") == "red"
    assert icon_name("~&@%+", "~") == "purple"
    assert icon_name("~&@%+", "~@+") == "purple"
    assert icon_name("!~&@%+", "!") is None
    assert icon_name("@%+", "") is None


def test_country_lookup():
    from bchat.countries import country_of
    assert country_of("root@netadmin.bajubesi.org") == "Internic Non-Profit Organization"
    assert country_of("x@a.my") == "Malaysia"
    assert country_of("x@1.2.3.4") == "Unknown"
    assert country_of("") == "Unknown"


def test_default_theme_is_mocha_and_import_keeps_it(tmp_path: Path):
    src = tmp_path / "XChat-SE"
    src.mkdir()
    (src / "colors.conf").write_text("color_259 = 0000 0000 0000\ncolor_0 = ffff 0000 0000\n")
    (src / "servlist.conf").write_text("N=SkinIRC\nF=45\nS=znc.a.my/+5599\n")
    cfg = Config()
    assert cfg.theme.chat_bg == "#1e1e2e" and cfg.theme.nick == "#b4befe"
    import_into(cfg, [src])
    assert cfg.theme.chat_bg == "#1e1e2e" and cfg.theme.palette[0] == "#cdd6f4"
    assert cfg.networks[0].name == "SkinIRC"


def test_no_old_colours_left_in_stylesheet():
    from bchat.widgets import stylesheet
    css = stylesheet(Config().theme)
    for old in ("#2a2c31", "#26282d", "#33353b", "#44474e", "#55585f", "#65686f", "#202226", "#17181b"):
        assert old not in css


def test_parse_server_forms():
    from bchat.commands import parse_server
    assert parse_server(["irc.x.org"]) == ("irc.x.org", 6667, False, "")
    assert parse_server(["-ssl", "irc.x.org"]) == ("irc.x.org", 6697, True, "")
    assert parse_server(["irc.x.org", "7000"]) == ("irc.x.org", 7000, False, "")
    assert parse_server(["irc.x.org", "+7000"]) == ("irc.x.org", 7000, True, "")
    assert parse_server(["irc.x.org/+5599"]) == ("irc.x.org", 5599, True, "")
    assert parse_server(["irc.x.org", "6667", "pw"]) == ("irc.x.org", 6667, False, "pw")
    assert parse_server(["-ssl"]) is None


def test_owner_and_admin_count_as_op_for_the_strip():
    order = "~&@%+"
    for rank, expect in (("~", True), ("&", True), ("@", True), ("%", False), ("+", False)):
        assert (order.index(rank) <= order.index("@")) is expect


def _nicklist_row(dpr: float, prefixes: str):
    """One 19 px nick-list row painted at a display scale: (light's top/left, nick's left), in logical px."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem
    from bchat.config import Theme
    from bchat.session import User
    from bchat.userlist import UserDelegate, UserModel

    class Buf:
        class session:
            prefix_order = "@%+"

        def sorted_users(self):
            return [User("Belon", prefixes, "")]

    t = Theme()
    m = UserModel()
    m.set_buffer(Buf())
    img = QImage(round(120 * dpr), round(19 * dpr), QImage.Format.Format_RGB32)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    p.setFont(QFont("Tahoma", 8))
    o = QStyleOptionViewItem()
    o.rect = QRect(0, 0, 120, 19)
    o.fontMetrics = p.fontMetrics()
    UserDelegate(t, None).paint(p, o, m.index(0))
    p.end()
    lit = lambda x, y: QColor(img.pixel(x, y)).saturation() > 90           # the coloured light, not the grey text
    ink = lambda x, y: QColor(img.pixel(x, y)).lightness() > 60
    W, H = img.width(), img.height()
    light = [(x, y) for y in range(H) for x in range(round(13 * dpr)) if lit(x, y)]
    text = [x for x in range(round(13 * dpr), W) for y in range(H) if ink(x, y)]
    top = min(y for _, y in light) / dpr if light else None
    left = min(x for x, _ in light) / dpr if light else None
    return top, left, min(text) / dpr


def test_nicklist_light_and_nick_sit_where_xchat_puts_them(app):
    """Measured on the user's live XChat 2.8.9 at 100 % (11-08): in a 19 px row the light's 8 px image is centred
    (top 5 px down, level with the nick's capitals), 3 px in from the list edge; the nick starts 15 px in.
    BChat had the light 2 px higher (3 down) and the nick 2 px further right (17)."""
    top, left, nick = _nicklist_row(1.0, "@")
    assert 5 <= top <= 6, top                      # the light's soft top row is 5 or its first solid row is 6
    assert 3 <= left <= 4, left
    assert 15 <= nick <= 16, nick                  # Tahoma's B has a 1 px side bearing at most
    t15, l15, n15 = _nicklist_row(1.5, "+")        # the same spot on the user's 150 % screen
    assert abs(t15 - top) <= 1 and abs(n15 - nick) <= 1


def test_every_light_has_the_glass_shading(app):
    from PySide6.QtGui import QColor, QImage
    from bchat.userlist import LIGHT_SIZES
    from bchat.widgets import ASSETS
    for name in ("op", "voice", "hop", "red", "purple"):
        for px in LIGHT_SIZES:
            img = QImage(str(ASSETS / "lights" / f"{name}-{px}.png"))
            assert (img.width(), img.height()) == (px, px), (name, px)
            top = QColor(img.pixelColor(px // 2, px // 4))        # the pale glass dome
            mid = QColor(img.pixelColor(px // 2, px // 2))
            low = QColor(img.pixelColor(px // 2, px - 2))         # the glow at the bottom
            assert mid.alpha() == 255, (name, px)                 # opaque: the dark list must not show through
            assert top.saturationF() < low.saturationF(), (name, px, top.name(), low.name())
            assert low.valueF() > mid.valueF() or px < 9, (name, px, mid.name(), low.name())
            assert low.valueF() > 0.7, (name, px, low.name())
            assert img.pixelColor(0, 0).alpha() < 40              # round, not square


def test_light_is_picked_for_the_display_scale(app):
    from bchat.userlist import light_pixmap
    for dpr, px in ((1.0, 7), (1.25, 9), (1.5, 11), (1.75, 12), (2.0, 14), (2.5, 18), (3.0, 21), (1.3, 9)):
        pm = light_pixmap("op", dpr)
        assert pm.width() == px and pm.devicePixelRatio() == dpr
    assert light_pixmap(None, 1.5) is None


def test_app_icon_has_small_sizes_and_clear_corners(app):
    from PIL import Image
    from bchat.widgets import ASSETS
    ico = Image.open(ASSETS / "bchat.ico")
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])
    png = Image.open(ASSETS / "bchat.png").convert("RGBA")
    w = png.width
    for c in ((0, 0), (w - 1, 0), (0, w - 1), (w - 1, w - 1)):
        assert png.getpixel(c)[3] == 0
    assert png.getpixel((w // 2, w // 2))[3] > 200


def test_header_logo_has_no_background_and_every_scale(app):
    from PIL import Image
    from bchat.widgets import ASSETS, header_logo
    for h in (16, 20, 24, 28, 32, 40, 48):
        im = Image.open(ASSETS / "header" / f"logo-{h}.png").convert("RGBA")
        assert im.height == h
        w = im.width
        for c in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            assert im.getpixel(c)[3] < 40, (h, c)
    big = Image.open(ASSETS / "header/logo-48.png").convert("RGBA")
    assert any(p[3] > 200 for p in big.getdata())
    assert sum(p[3] < 10 for p in big.getdata()) > big.width * big.height * 0.1  # transparent around the B, no box
    for dpr, h in ((1.0, 16), (1.25, 20), (1.5, 24), (2.0, 32), (3.0, 48)):
        pm = header_logo(dpr)
        assert pm.height() == h and pm.devicePixelRatio() == dpr


def test_taskbar_icon_is_the_users_bold_logo():
    """The user's current transparent set (assets/logo/pinkblue since 11-07 ~11:30) is the app, taskbar and installer icon."""
    from PIL import Image, ImageChops
    from bchat.widgets import ASSETS
    root = ASSETS.parents[1] / "assets/logo/pinkblue/transparent"
    shipped = Image.open(ASSETS / "bchat.png").convert("RGBA")
    theirs = Image.open(root / "BChat_256.png").convert("RGBA")
    assert ImageChops.difference(shipped, theirs).getbbox() is None
    assert (ASSETS / "bchat.ico").read_bytes() == (root / "BChat.ico").read_bytes()

def test_ticked_checkbox_has_a_real_tick():
    """User: ticked boxes were only a slightly lighter grey. Now a sapphire box with a dark tick."""
    from bchat.config import Theme
    from bchat.widgets import ASSETS, stylesheet
    t = Theme()
    css = stylesheet(t)
    assert (ASSETS / "tick.png").exists()
    assert f"QCheckBox::indicator:checked {{ background: {t.check};" in css and "tick-11111b.svg" in css     # sharp at any scale


def test_popup_opens_above_when_no_room_below():
    """User: the emoji popup by the input box went under the taskbar when maximized."""
    from PySide6.QtCore import QRect, QSize
    from bchat.topicbar import place
    screen = QRect(0, 0, 1920, 1040)                       # work area above a 40 px taskbar
    size = QSize(180, 170)
    # topic bar button near the top: opens below
    assert place(QRect(1500, 80, 26, 24), size, screen).y() == 104
    # input box button at the bottom, maximized: opens above, fully on screen
    p = place(QRect(1880, 1010, 26, 24), size, screen)
    assert p.y() == 1010 - 170 and p.y() + size.height() <= 1040
    assert p.x() + size.width() <= 1920                    # pushed in from the right edge
    # odd case: no room either way still stays inside the screen
    small = QRect(0, 0, 400, 200)
    p = place(QRect(10, 90, 26, 24), size, small)
    assert 0 <= p.y() and p.y() + size.height() <= 200


def test_mirc_extended_hex_strike_and_mono():
    """mIRC study bugs 1-3 (11-07): colours 16-98 wrapped to 0-15, hex colours printed as text, \x1e \x11 dropped."""
    from bchat.protocol import EXTENDED, colour_of
    pal = [f"#00000{i:x}" for i in range(16)]
    s = parse_format("\x0320,52a\x03 \x04FF8800,000000b\x04 \x1ec\x1e \x11d\x11 \x0399e")
    got = {x.text: x for x in s if x.text.strip()}
    assert (got["a"].fg, got["a"].bg) == (20, 52)
    assert colour_of(20, pal) == "#004700" and colour_of(52, pal) == "#ff0000"   # fixed, not the theme's 4 and 4
    assert colour_of(4, pal) == pal[4] and colour_of(99, pal) is None and colour_of(None, pal) is None
    assert len(EXTENDED) == 83 and colour_of(98, pal) == "#ffffff" and colour_of(16, pal) == "#470000"
    assert (got["b"].fg, got["b"].bg) == ("#ff8800", "#000000") and colour_of("#ff8800", pal) == "#ff8800"
    assert got["c"].strike and not got["d"].strike and got["d"].mono and not got["e"].mono
    assert got["e"].fg == 99 and colour_of(99, pal) is None
    assert strip_format("\x04FF8800orange\x04 \x1estruck\x1e") == "orange struck"    # no hex digits left in the text
    assert strip_format("\x04 x") == " x"                                            # bare \x04 just resets


def test_readable_keeps_hue_and_leaves_good_colours_alone():
    from bchat.config import THEME_NAMES, make_theme
    from bchat.protocol import EXTENDED, contrast, readable
    for name in THEME_NAMES:
        bg = make_theme(name).chat_bg
        for h in EXTENDED:
            out = readable("#" + h, bg)
            assert contrast(out, bg) >= 2.99, (name, h, out)
            if contrast("#" + h, bg) >= 3:
                assert out == "#" + h                                  # readable colours are never touched
    assert readable("#ffffff", "#202040") == "#ffffff"
    assert readable("#474700", "#1e1e2e") == "#7a7a00"                 # dark olive -> lighter olive, not grey
