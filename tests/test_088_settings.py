"""0.8.8 Settings layout: pages scroll and fit the screen, Trusted people page, Network setup rows."""
import pytest
from PySide6.QtWidgets import QApplication, QTableWidget

from test_live import make_win


def settle(app, ms=30):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def dialog(app, tmp_path):
    from bchat.preferences import PreferencesDialog
    win, _ = make_win(tmp_path, 1)
    made = []

    def make(page="Network setup"):
        d = PreferencesDialog(win, page)
        d.show()
        settle(app)
        made.append(d)
        return d
    yield make
    for d in made:
        d.reject()
    win.close()


def label(grid, row):
    return grid.itemAtPosition(row, 0).widget()


def test_proxy_off_shows_only_the_type(app, dialog):
    d = dialog()
    d.proxy_type.setCurrentIndex(0)
    settle(app)
    assert d.proxy_type.isVisible()
    for w in (d.proxy_host, d.proxy_port, d.proxy_auth, d.proxy_user, d.proxy_pass, d.proxy_no_pass,
              label(d._proxy_grid, 1), label(d._proxy_grid, 2)):
        assert not w.isVisible(), w


@pytest.mark.parametrize("index", [1, 2])                 # Socks5, HTTP
def test_socks5_and_http_ask_for_a_login_only_when_ticked(app, dialog, index):
    d = dialog()
    d.proxy_type.setCurrentIndex(index)
    d.proxy_auth.setChecked(False)
    settle(app)
    assert d.proxy_host.isVisible() and d.proxy_port.isVisible() and d.proxy_auth.isVisible()
    assert not d.proxy_user.isVisible() and not d.proxy_pass.isVisible()
    d.proxy_auth.setChecked(True)
    settle(app)
    assert d.proxy_user.isVisible() and d.proxy_pass.isVisible() and not d.proxy_no_pass.isVisible()
    assert label(d._login_grid, 0).text() == "Username:"


@pytest.mark.parametrize("index", [3, 4])                 # Socks4, Socks4a
def test_socks4_shows_a_user_id_and_no_password(app, dialog, index):
    d = dialog()
    d.proxy_auth.setChecked(False)
    d.proxy_type.setCurrentIndex(index)
    settle(app)
    assert not d.proxy_auth.isVisible()                    # Socks4 sends the User ID whatever the tick says
    assert d.proxy_user.isVisible() and label(d._login_grid, 0).text() == "User ID:"
    assert not d.proxy_pass.isVisible() and d.proxy_no_pass.isVisible()
    assert d.proxy_no_pass.text() == "Socks4 has no password"
    d.proxy_type.setCurrentIndex(1)                        # back to Socks5: the old label returns
    d.proxy_auth.setChecked(True)
    settle(app)
    assert label(d._login_grid, 0).text() == "Username:" and d.proxy_pass.isVisible()


def test_ident_user_id_is_greyed_until_ticked(app, dialog):
    d = dialog()
    d.identd_on.setChecked(False)
    assert not d.identd_user.isEnabled() and not d._ident_label.isEnabled()
    d.identd_on.setChecked(True)
    assert d.identd_user.isEnabled() and d._ident_label.isEnabled()


def test_new_headings_and_router_wording(app, dialog):
    from PySide6.QtWidgets import QLabel
    d = dialog()
    texts = [w.text() for w in d.page_widget("Network setup").findChildren(QLabel)]
    assert any(t.startswith("<b>Ident <span") and "(identification)" in t for t in texts)
    assert any(t.startswith("<b>Router <span") and "(UPnP)" in t for t in texts)
    assert not any("Proxy Authentication" in t or "Ident Server" in t for t in texts)
    assert d.upnp_on.text() == "Open file-transfer ports on my router automatically"


@pytest.mark.parametrize("text, dot, colour", [
    ("Router found · outside address 203.0.113.7 · 2 ports open", "●", "status_on"),
    ("Router found, but it refused to open the ports (ConflictInMappingEntry (718))", "●", "status_off"),
    ("No router answered (UPnP)", "○", "muted"),
])
def test_router_status_has_a_coloured_dot(app, dialog, text, dot, colour):
    d = dialog()
    d.upnp_on.setChecked(True)
    d._upnp_status_changed(text)
    settle(app)
    shown = d.upnp_status.text()
    want = getattr(d.win.cfg.theme, colour)
    assert d.upnp_status.isVisible()
    assert shown.startswith(f"<span style='color: {want}'>{dot}</span>"), shown
    assert "203.0.113.7" in shown or "718" in shown or "No router" in shown


def test_router_status_hides_with_the_tick_and_escapes_text(app, dialog):
    d = dialog()
    d.upnp_on.setChecked(True)
    d._upnp_status_changed("Router found, but it refused to open the ports (<b>718</b>)")
    settle(app)
    assert d.upnp_status.isVisible() and "&lt;b&gt;" in d.upnp_status.text()
    d.upnp_on.setChecked(False)
    settle(app)
    assert not d.upnp_status.isVisible()
    d.upnp_on.setChecked(True)                             # the last status comes back with the tick
    settle(app)
    assert d.upnp_status.isVisible()
    d._upnp_status_changed("")
    settle(app)
    assert not d.upnp_status.isVisible()


def test_trusted_people_is_its_own_page_under_file_transfers(app, dialog):
    d = dialog("Trusted people")
    item = d._items["Trusted people"]
    assert item.parent() is d._items["File transfers"] and d._items["File transfers"].isExpanded()
    assert d.page_widget("Trusted people").isAncestorOf(d.trust_list)
    files = d.page_widget("File transfers")
    assert not files.findChildren(QTableWidget)            # the list moved off the File transfers page
    assert d.pages.currentIndex() == d.page_of["Trusted people"]


def test_dialog_fits_the_tallest_page_or_85_percent_of_the_screen(app, dialog):
    from bchat.preferences import PAGE_FIT
    d = dialog()
    screen = d.screen() or QApplication.primaryScreen()
    most = int(screen.availableGeometry().height() * PAGE_FIT)
    assert d.height() <= max(420, most)
    tallest = max(d.pages.widget(i).widget().minimumSizeHint().height() for i in range(d.pages.count()))
    viewport = d.pages.currentWidget().viewport().height()
    if d.height() < max(420, most):                        # not capped: no page needs to scroll
        assert tallest <= viewport, (tallest, viewport)
    for i in range(d.pages.count()):                       # never sideways
        area = d.pages.widget(i)
        assert area.widget().minimumSizeHint().width() <= area.viewport().width() or not area.isVisible()


def test_short_screens_scroll_instead_of_overflowing(app, dialog, monkeypatch):
    from bchat import preferences
    monkeypatch.setattr(preferences, "PAGE_FIT", 0.3)
    d = dialog("File transfers")
    screen = d.screen() or QApplication.primaryScreen()
    assert d.height() == max(420, int(screen.availableGeometry().height() * 0.3))
    area = d.pages.currentWidget()
    assert area.verticalScrollBar().maximum() > 0          # the page scrolls
    last = d.page_widget("File transfers").findChildren(type(d.proxy_type))[-1]
    area.ensureWidgetVisible(last)
    settle(app)
    assert last.visibleRegion().boundingRect().size() == last.size()
