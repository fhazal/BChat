"""The nick list: 19 px rows, XChat's status lights centred in the row (GTK's cell centring), away nicks grey."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from .config import Theme
from .session import Buffer, User
from .widgets import ASSETS



def icon_name(order: str, prefixes: str) -> str | None:
    """XChat's get_user_icon: @ % + are fixed, one level above @ is red, two above is purple, higher has none."""
    rank = next((c for c in order if c in prefixes), None)
    if rank is None:
        return None
    fixed = {"@": "op", "%": "hop", "+": "voice"}.get(rank)
    if fixed or "@" not in order:
        return fixed
    level = order.index("@") - order.index(rank) - 1
    return {0: "red", 1: "purple"}.get(level)


LIGHT_SIZES = (7, 9, 11, 12, 14, 18, 21)
_lights: dict[tuple[str, int], QPixmap] = {}


def light_pixmap(name: str | None, dpr: float) -> QPixmap | None:
    """The status light made for this display scale, so it is drawn pixel for pixel with no blur."""
    if name is None:
        return None
    px = min(LIGHT_SIZES, key=lambda s: abs(s - 7 * dpr))
    key = (name, round(dpr * 100))
    pm = _lights.get(key)
    if pm is None:
        pm = QPixmap(str(ASSETS / "lights" / f"{name}-{px}.png"))
        pm.setDevicePixelRatio(dpr)
        _lights[key] = pm
    return pm


class UserModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.users: list[User] = []
        self.buffer: Buffer | None = None

    def set_buffer(self, b: Buffer | None) -> None:
        self.beginResetModel()
        self.buffer = b
        self.users = b.sorted_users() if b is not None else []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.users)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        u = self.users[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return u.nick
        if role == Qt.ItemDataRole.ToolTipRole:
            return u.host or None
        if role == Qt.ItemDataRole.UserRole:
            return u
        return None


class UserDelegate(QStyledItemDelegate):
    ROW = 19
    ICON = 7
    LEFT = 3   # light's left edge
    TEXT = 15  # nick's left edge, as XChat

    def __init__(self, theme: Theme, parent=None, cfg=None):
        super().__init__(parent)
        self.theme = theme
        self.cfg = cfg

    def sizeHint(self, option, index):
        # a bigger chat font needs taller rows
        return QSize(40, max(self.ROW, option.fontMetrics.height() + 3))

    def paint(self, p: QPainter, option, index):
        u: User = index.data(Qt.ItemDataRole.UserRole)
        r = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            p.fillRect(r, QColor(self.theme.selected))
        # highest rank wins when the server sends several prefixes
        model = index.model()
        order = model.buffer.session.prefix_order if model.buffer else "@%+"
        dpr = p.device().devicePixelRatioF()
        pm = light_pixmap(icon_name(order, u.prefixes), dpr)
        if pm is not None:
            # XChat 2.8.9 measured at 100 %: GTK centres its 8 px light image in the row, 3 px in from the list edge
            # (in a 19 px row: 5 down, its top level with the nick's capitals). Lined up with real screen pixels,
            # or the shine would smear at 125 and 150 %.
            x, y = round((r.x() + self.LEFT) * dpr) / dpr, round((r.y() + (r.height() - 8) // 2) * dpr) / dpr
            p.drawPixmap(QPointF(x, y), pm)
        col = self.theme.marking_fg if selected else (self.theme.away if u.away else self.theme.text)
        p.setPen(QColor(col))
        tr = QRect(r.x() + self.TEXT, r.y(), r.width() - self.TEXT, r.height())
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, u.nick)
        if self.cfg is not None and self.cfg.ul_hosts and u.host:
            x = p.fontMetrics().horizontalAdvance(u.nick) + 10
            p.setPen(QColor(self.theme.marking_fg if selected else self.theme.away))
            p.drawText(tr.adjusted(x, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, u.host)


class UserList(QListView):
    def __init__(self, theme: Theme, parent=None, cfg=None):
        super().__init__(parent)
        self.model_ = UserModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(UserDelegate(theme, self, cfg))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def set_buffer(self, b: Buffer | None) -> None:
        keep = {u.nick for u in self.selected_users()}
        top = self.verticalScrollBar().value()
        self.model_.set_buffer(b)
        sm = self.selectionModel()
        for i, u in enumerate(self.model_.users):
            if u.nick in keep:
                sm.select(self.model_.index(i), sm.SelectionFlag.Select)
        self.verticalScrollBar().setValue(top)

    def selected_users(self) -> list[User]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.selectedIndexes()]
