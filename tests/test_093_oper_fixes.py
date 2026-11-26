"""0.9.3 oper fixes: Ban from server with no nick takes a typed nick or mask, the Global notice goes through
services where the server has no NOTICE $*, your own wallops show without +w, and the Server bans window
reads OperServ's AKILL / ZLINE / SHUN lists on BeeIRCd."""
from bchat.oper import BanDialog, MessageDialog, global_lines, open_server_bans
from test_093_oper import ME, VERSIONS, connected, done, join_people, make_oper
from test_live import wait

OS = ":OperServ!services@services.skinirc.net NOTICE " + ME + " :"


# --- Global notice ------------------------------------------------------------------------------------

def test_global_lines_per_server_and_services():
    assert global_lines("beeircd", "Restart") == ["PRIVMSG OperServ :GLOBAL Restart"]
    assert global_lines("beeircd", "Restart", "server") == ["PRIVMSG OperServ :GLOBAL Restart"]
    assert global_lines("inspircd", "Restart") == ["NOTICE $* :Restart"]
    assert global_lines("charybdis", "Restart", "server", "atheme") == ["NOTICE $$* :Restart"]
    assert global_lines("unreal", "Restart", "services", "anope") == ["PRIVMSG Global :GLOBAL Restart"]
    assert global_lines("unreal", "Restart", "services", "") == ["PRIVMSG Global :GLOBAL Restart"]
    assert global_lines("charybdis", "Restart", "services", "atheme") == ["PRIVMSG OperServ :GLOBAL Restart",
                                                                         "PRIVMSG OperServ :GLOBAL SEND"]


def test_global_notice_on_beeircd_goes_through_operserv_with_no_choice(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    d = MessageDialog(win, s, "global")
    assert not d.via.isVisibleTo(d)
    d.text.setText("Restart  at noon")
    assert d.sends.text() == "PRIVMSG OperServ :GLOBAL Restart at noon"
    d.go.click()
    assert wait(app, lambda: "PRIVMSG OperServ :GLOBAL Restart at noon" in srv.received)
    assert not any(x.startswith("NOTICE $") for x in srv.received)
    assert s.net.name not in win.cfg.oper_global_via
    done(srv, win)


def test_global_notice_via_services_is_remembered_per_network(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["unreal"])
    make_oper(app, srv, s)
    d = MessageDialog(win, s, "global")
    assert d.via.isVisibleTo(d) and d.via.currentData() == "server"
    d.text.setText("Restart at noon")
    assert d.sends.text() == "NOTICE $* :Restart at noon"
    d.via.setCurrentIndex(1)
    assert d.sends.text() == "PRIVMSG Global :GLOBAL Restart at noon"
    d.go.click()
    assert wait(app, lambda: "PRIVMSG Global :GLOBAL Restart at noon" in srv.received)
    assert win.cfg.oper_global_via[s.net.name] == "services"
    d = MessageDialog(win, s, "global")                        # opened again: Services is still picked
    assert d.via.currentData() == "services"
    d.reject()
    done(srv, win)


def test_global_notice_via_atheme_sends_global_and_send(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["solanum"])
    make_oper(app, srv, s)
    s.services = "atheme"
    d = MessageDialog(win, s, "global")
    d.via.setCurrentIndex(1)
    d.text.setText("Restart")
    assert d.sends.text() == "PRIVMSG OperServ :GLOBAL Restart\nPRIVMSG OperServ :GLOBAL SEND"
    d.go.click()
    assert wait(app, lambda: "PRIVMSG OperServ :GLOBAL SEND" in srv.received)
    assert srv.received.index("PRIVMSG OperServ :GLOBAL Restart") < srv.received.index("PRIVMSG OperServ :GLOBAL SEND")
    done(srv, win)


# --- Wallops ------------------------------------------------------------------------------------------

def wallops_shown(s, text):
    return [l for l in s.server_buffer.lines if text in l.text]


def test_own_wallops_show_when_you_dont_have_plus_w(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    assert not s.wallops_on
    d = MessageDialog(win, s, "wallops")
    assert not d.via.isVisibleTo(d)
    d.text.setText("Netsplit coming")
    d.go.click()
    assert wait(app, lambda: "WALLOPS :Netsplit coming" in srv.received)
    assert len(wallops_shown(s, "Netsplit coming")) == 1
    done(srv, win)


def test_own_wallops_are_not_shown_twice_with_plus_w(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    srv.send(f":{ME} MODE {ME} :+w")
    assert wait(app, lambda: s.wallops_on)
    d = MessageDialog(win, s, "wallops")
    d.text.setText("Netsplit coming")
    d.go.click()
    assert wait(app, lambda: "WALLOPS :Netsplit coming" in srv.received)
    assert not wait(app, lambda: bool(wallops_shown(s, "Netsplit coming")), 300)   # the server sends it back itself
    srv.send(f":{ME} MODE {ME} :-w")
    assert wait(app, lambda: not s.wallops_on)
    srv.send(f":srv 221 {ME} +iowx")
    assert wait(app, lambda: s.wallops_on)
    done(srv, win)


# --- Ban from server with no nick -------------------------------------------------------------------

def items(d):
    return [d.mask_box.itemText(i) for i in range(d.mask_box.count())]


def test_ban_dialog_with_no_nick_starts_empty_with_a_hint(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    d = BanDialog(win, s)
    assert d.mask_box.currentText() == "" and items(d) == []
    assert d.mask_box.lineEdit().placeholderText() == "nick, or *@1.2.3.4"
    assert d.sends.text() == "Type a nick or a mask (user@host) in Ban:" and not d.go.isEnabled()
    d.kind.setCurrentIndex(1)                                  # ZLINE: an IP
    assert d.mask_box.lineEdit().placeholderText() == "nick, or 1.2.3.4"
    assert d.sends.text() == "Type a nick or an IP address in Ban:"
    d.reject()
    done(srv, win)


def test_ban_dialog_typed_mask_and_typed_nick(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    join_people(app, srv, s)
    d = BanDialog(win, s)
    d.mask_box.setEditText("*@198.51.100.4")
    assert d.go.isEnabled() and d.sends.text().startswith("GLINE *@198.51.100.4 ")
    d.mask_box.setEditText("zed")                              # a nick in our channel: its masks are offered
    assert items(d) == ["*@203.0.113.7", "*@203.0.113.*", "~z@203.0.113.7"]
    assert d.mask_box.currentText() == "zed" and d.go.isEnabled()
    assert d.sends.text().startswith("GLINE *@203.0.113.7 ")
    assert "zed is zed!~z@203.0.113.7" in d.why.text()
    d.mask_box.setCurrentIndex(1)                              # picking another of the offered masks keeps the list
    assert items(d) == ["*@203.0.113.7", "*@203.0.113.*", "~z@203.0.113.7"]
    assert d.sends.text().startswith("GLINE *@203.0.113.* ")
    d.mask_box.setEditText("nobodyhere")
    assert items(d) == [] and not d.go.isEnabled() and "No one called nobodyhere" in d.why.text()
    d.kind.setCurrentIndex(1)                                  # ZLINE on a typed nick: the IP
    d.mask_box.setEditText("bob")
    assert items(d) == ["192.0.2.9"] and d.sends.text().startswith("ZLINE 192.0.2.9 ")
    d.go.click()
    assert wait(app, lambda: any(x.startswith("ZLINE 192.0.2.9 ") for x in srv.received))
    done(srv, win)


# --- Server bans: OperServ's lists ------------------------------------------------------------------

def rows(w):
    return [[w.view.topLevelItem(i).text(c) for c in range(3)] for i in range(w.view.topLevelItemCount())]


def test_server_bans_reads_operserv_lists_on_beeircd(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    w = open_server_bans(win, s)
    assert wait(app, lambda: "PRIVMSG OperServ :SHUN LIST" in srv.received)
    srv.send(f":srv 216 {ME} K bad.host * baduser :Spam")
    srv.send(f":srv 219 {ME} k :End of /STATS report")
    srv.send(OS + "AKILLs:")
    srv.send(OS + "  1   *@10.9.9.9  by TestOper · 24 hours left · spam bots")
    srv.send(OS + "  2   ~x@198.51.100.*  by TestOper · until removed · flood · again")
    srv.send(OS + "2 AKILLs.")
    srv.send(OS + "No ZLINEs.")
    assert wait(app, lambda: len(rows(w)) == 3)
    assert s.oper_sink is not None                              # SHUN still to come
    srv.send(OS + "SHUNs:")
    srv.send(OS + "  1   *@192.0.2.5  by TestOper · 2 hours left · noisy")
    srv.send(OS + "1 SHUN.")
    assert wait(app, lambda: s.oper_sink is None)
    got = rows(w)
    assert ["GLINE", "*@10.9.9.9", "spam bots  (24 hours left)"] in got
    assert ["GLINE", "~x@198.51.100.*", "flood · again  (until removed)"] in got
    assert ["SHUN", "*@192.0.2.5", "noisy  (2 hours left)"] in got
    assert not any("AKILL" in l.text or "SHUN" in l.text for b in s.all_buffers() for l in b.lines)
    w.view.setCurrentItem(w.view.topLevelItem(1))
    w.remove()
    assert wait(app, lambda: "GLINE -*@10.9.9.9" in srv.received)
    done(srv, win)


def test_operserv_notices_still_show_when_the_bans_window_isnt_reading(app, tmp_path):
    srv, win, s = connected(app, tmp_path, VERSIONS["beeircd"])
    make_oper(app, srv, s)
    srv.send(OS + "No AKILLs.")
    assert wait(app, lambda: any("No AKILLs." in l.text for b in s.all_buffers() for l in b.lines))
    w = open_server_bans(win, s)
    assert wait(app, lambda: "PRIVMSG OperServ :SHUN LIST" in srv.received)
    srv.send(OS + "Password accepted.")                         # not part of a list: left alone
    assert wait(app, lambda: any("Password accepted." in l.text for b in s.all_buffers() for l in b.lines))
    w.hide()
    done(srv, win)
