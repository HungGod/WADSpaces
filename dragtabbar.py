import json
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QStyle

class DragTabBar(QtWidgets.QTabBar):
    tabDetachRequested = QtCore.Signal(int, QtCore.QPoint)
    tabInsertRequested = QtCore.Signal(object, int, int)
    plusClicked = QtCore.Signal()  
    
    APP_MIME = "application/browserlessPWA"
    BASE_TAB_W = 160
    MIN_TAB_W  = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        # + button first
        self._uniform_tab_width = self.BASE_TAB_W
        self._last_applied_width = -1

        self._plus = QtWidgets.QToolButton(self)
        self._plus.setText("")
        self._plus.setIcon(QtGui.QIcon(":/add-tab.svg"))
        self._plus.setIconSize(QtCore.QSize(16, 16))
        self._plus.setAutoRaise(True)
        self._plus.setToolTip("New tab")
        self._plus.clicked.connect(self.plusClicked.emit)

        h = max(18, super().sizeHint().height() - 2)
        self._plus.resize(h, h)

        # tabbar config — start with scroll OFF
        self.setAcceptDrops(True)
        self.setMovable(False)
        self.setElideMode(QtCore.Qt.ElideRight)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setTabsClosable(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        self._drag_start_index: int | None = None
        self._drag_start_pos: QtCore.QPoint | None = None
        self._drag_window: bool | None = None
        
        # insertion indicator
        self._dropIndicator = QtWidgets.QFrame(self)
        self._dropIndicator.setObjectName("dropIndicator")
        self._dropIndicator.setStyleSheet("""
            QFrame#dropIndicator {
                background: #0a84ff;
            }
        """)
        self._dropIndicator.setFixedWidth(2)   # thin vertical bar
        self._dropIndicator.hide()

        self._pendingDstIndex = -1
    # --- sizing helpers -------------------------------------------------------
    def tabSizeHint(self, index: int) -> QtCore.QSize:
        s = super().tabSizeHint(index)
        return QtCore.QSize(self._uniform_tab_width, s.height())

    def _scroll_buttons_total_width(self) -> int:
        if not self.usesScrollButtons():
            return 0
        bw = self.style().pixelMetric(QStyle.PM_TabBarScrollButtonWidth, None, self)
        return bw * 2

    def _available_width_for_tabs(self) -> int:
        m = self.style().pixelMetric(QStyle.PM_DefaultFrameWidth)
        return max(0, self.width() - self._plus.width() - self._scroll_buttons_total_width() - m*2 - 8)

    def _recompute_uniform_width(self):
        # total width needed at base size
        n = max(1, self.count())
        avail = self._available_width_for_tabs()
        need  = n * self.BASE_TAB_W

        if need <= avail:
            target = self.BASE_TAB_W
        else:
            target = max(self.MIN_TAB_W, avail // n)

        # Only apply if it actually changes (prevents visible jitter)
        if target != self._last_applied_width:
            self._uniform_tab_width = target
            self._last_applied_width = target
            self.updateGeometry()
            self.update()

    def _reposition_plus(self):
        m = self.style().pixelMetric(QStyle.PM_DefaultFrameWidth)
        spacing = 1

        # anchor to the right edge of the last *visible* tab (accounts for scrolling)
        if self.count() > 0:
            r = self.tabRect(self.count() - 1)
            x = r.right() + spacing
        else:
            x = m + spacing

        # keep inside right edge before scroll buttons
        right_limit = self.width() - self._scroll_buttons_total_width() - m - 2
        x = min(x, right_limit - self._plus.width())
        x = max(m, x)
        y = max(0, (self.height() - self._plus.height()) // 2)
        self._plus.move(x, y)

    def _relayout(self):
        self._recompute_uniform_width()
        self._reposition_plus()

    # events that can change geometry
    def resizeEvent(self, e):  super().resizeEvent(e);  self._relayout()
    def tabLayoutChange(self): super().tabLayoutChange(); self._relayout()
    def tabInserted(self, i):  super().tabInserted(i);  self._relayout()
    def tabRemoved(self, i):   super().tabRemoved(i);   self._relayout()
    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self._relayout)

    # --- Reordering within the same bar
    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            idx = self.tabAt(event.position().toPoint())
            if idx != -1:
                # prepare for tab drag (your logic)
                self._drag_start_index = idx
                self._drag_start_pos = event.position().toPoint()
                super().mousePressEvent(event)
                return

            # Empty area -> start window move (let compositor handle snapping/offscreen)
            wh = self.window().windowHandle() if self.window() else None
            if wh:
                # If maximized, restore first; KWin then continues the drag
                if self.window().isMaximized():
                    # Store the global cursor position and local click position BEFORE unmaximizing
                    global_cursor = event.globalPosition().toPoint()
                    local_click = event.position().toPoint()
                    # Unmaximize first
                    self.window().showNormal()
                    # update your maximize button if present
                    self.window()._maximize_btn.setText("□")
                    self.window()._maximize_btn.setToolTip("Maximize")
                    
                    # Force Qt to process the geometry change immediately
                    QtWidgets.QApplication.processEvents()
                    
                    n_bar_w = max(1, self.width())
                    # Now recalculate: map the same local click position to window coordinates
                    # after unmaximize (widget layout should be the same relative to window)
                    click_in_window_restored = self.mapTo(self.window(), local_click)
                    
                    # Position window so cursor stays at the same position within the window
                    # window_top_left = global_cursor - click_position_in_window
                    new_pos = global_cursor - click_in_window_restored
                    self.window().move(new_pos.x(), new_pos.y())
                    
                    # Process events again to ensure move is applied
                    QtWidgets.QApplication.processEvents()

                # Start native move *on press*, not in mouseMoveEvent
                wh.startSystemMove()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._drag_start_index is None:
            # previously you did: self.window().move(...). Remove that.
            super().mouseMoveEvent(event)

            return

        if (event.position().toPoint() - self._drag_start_pos).manhattanLength() < QtWidgets.QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()

        src_win = self.window()
        seq = src_win.new_drag_seq()

        # compute this window's index in Browser
        browser = src_win.browser()
        try:
            src_window_index = browser.windows().index(src_win)
        except ValueError:
            src_window_index = -1  # should not happen, but be defensive

        payload = {
            "src_window_index": src_window_index,
            "src_index": self._drag_start_index,
            "seq": seq,
        }
        mime.setData(self.APP_MIME, QtCore.QByteArray(json.dumps(payload).encode("utf-8")))
        drag.setMimeData(mime)

        # drag pixmap of the tab
        tab_rect = self.tabRect(self._drag_start_index)
        pm = QtGui.QPixmap(tab_rect.size())
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        self.render(p, QtCore.QPoint(), QtGui.QRegion(tab_rect))
        p.end()
        drag.setPixmap(pm)
        drag.setHotSpot(QtCore.QPoint(pm.width() // 2, pm.height() // 2))

        drag.exec(QtCore.Qt.DropAction.CopyAction | QtCore.Qt.DropAction.MoveAction,
                QtCore.Qt.DropAction.MoveAction)

        # If no one accepted, treat as detach.
        if not src_win.was_drag_seq_accepted(seq):
            global_pos = QtGui.QCursor.pos()
            self.tabDetachRequested.emit(self._drag_start_index, global_pos)

        self._drag_start_index = None
        self._drag_start_pos = None

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        # release cancels any armed-but-not-started drag
        self._drag_window = None
        self._drag_start_index = None
        self._drag_start_pos   = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            if self.tabAt(event.position().toPoint()) == -1:
                # double-click in empty strip area
                self.window()._toggle_maximize()    
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    # --- helper to compute insertion position for visual indicator
    def _indicator_rect_for_pos(self, pos: QtCore.QPoint) -> QtCore.QRect:
        idx = self.tabAt(pos)
        if idx < 0:
            # after last tab
            if self.count() == 0:
                return QtCore.QRect(6, 0, 2, self.height())
            last = self.tabRect(self.count() - 1)
            x = last.right() + 1
            return QtCore.QRect(x, 0, 2, self.height())

        r = self.tabRect(idx)
        left_half = pos.x() < r.center().x()
        x = r.left() if left_half else r.right()
        return QtCore.QRect(x, 0, 2, self.height())

    def _compute_dst_index(self, pos: QtCore.QPoint) -> int:
        idx = self.tabAt(pos)
        if idx < 0:
            return self.count()
        r = self.tabRect(idx)
        return idx if pos.x() < r.center().x() else idx + 1

    # --- DnD events (augment yours)
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if event.mimeData().hasFormat(self.APP_MIME):
            event.acceptProposedAction()
            # show indicator immediately
            rect = self._indicator_rect_for_pos(event.position().toPoint())
            self._dropIndicator.setGeometry(rect)
            self._dropIndicator.show()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if event.mimeData().hasFormat(self.APP_MIME):
            pos = event.position().toPoint()
            rect = self._indicator_rect_for_pos(pos)
            self._dropIndicator.setGeometry(rect)
            self._dropIndicator.show()
            self._pendingDstIndex = self._compute_dst_index(pos)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent):
        self._dropIndicator.hide()
        self._pendingDstIndex = -1
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        if not event.mimeData().hasFormat(self.APP_MIME):
            super().dropEvent(event)
            return

        # decode payload
        data = event.mimeData().data(self.APP_MIME)
        payload = json.loads(bytes(data).decode("utf-8"))
        src_window_index = payload.get("src_window_index", -1)
        src_index        = payload.get("src_index", -1)
        seq              = payload.get("seq")

        # compute destination index based on cursor (matches indicator)
        pos = event.position().toPoint()
        dst_index = self._compute_dst_index(pos)

        # look up windows
        browser = self.window().browser()
        dest_window = self.window()
        try:
            this_window_index = browser.windows().index(dest_window)
        except ValueError:
            this_window_index = -1

        # same-window move
        if src_window_index == this_window_index:
            # if moving forward, account for removal shifting indices
            if dst_index > src_index:
                dst_index -= 1
            self.window()._tab_widget.moveTab(src_index, max(0, dst_index))
            # mark acceptance on the *source* window (which is dest_window here)
            dest_window.mark_drag_seq_accepted(seq)

        else:
            # cross-window merge: emit with the TRUE source window
            try:
                src_window = browser.windows()[src_window_index]
            except Exception:
                src_window = None

            if src_window is None:
                event.ignore()
                self._dropIndicator.hide()
                self._pendingDstIndex = -1
                return

            # tell parent (TabWidget) to pull the tab from src_window
            self.tabInsertRequested.emit(src_window, src_index, dst_index)
            # mark acceptance on the source window so it won't detach
            src_window.mark_drag_seq_accepted(seq)

        event.acceptProposedAction()

        # cleanup indicator
        self._dropIndicator.hide()
        self._pendingDstIndex = -1
        self._pendingDstIndex = -1