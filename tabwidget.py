from __future__ import annotations

from functools import partial

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QUrl, Qt, Signal, Slot
from PySide6.QtGui import QCursor, QIcon, QKeySequence
from PySide6.QtWebEngineCore import QWebEngineFindTextResult, QWebEnginePage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QMenu, QTabBar, QStackedWidget
)

from dragtabbar import DragTabBar
from webpage import WebPage
from webview import WebView

class TabWidget(QWidget):
    title_changed = Signal(str)
    link_hovered = Signal(str)
    load_progress = Signal(int)
    url_changed = Signal(QUrl)
    fav_icon_changed = Signal(QIcon)
    web_action_enabled_changed = Signal(QWebEnginePage.WebAction, bool)
    dev_tools_requested = Signal(QWebEnginePage)
    find_text_finished = Signal(QWebEngineFindTextResult)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self._profile = profile

        # --- internals: a tab strip + a stack of page widgets
        self._tabbar = DragTabBar(self)
        self._stack = QStackedWidget()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._tabbar)
        lay.addWidget(self._stack, 1)

        # wiring (replacing old QTabWidget signals)
        self._tabbar.plusClicked.connect(parent._new_tab)
        self._tabbar.tabDetachRequested.connect(parent.detach_tab_to_new_window)
        self._tabbar.tabInsertRequested.connect(parent.receive_tab_from)

        self._tabbar.currentChanged.connect(self.handle_current_changed)
        self._tabbar.currentChanged.connect(self._stack.setCurrentIndex)
        self._tabbar.tabCloseRequested.connect(self.close_tab)
        self._tabbar.customContextMenuRequested.connect(self.handle_context_menu_requested)

    # ---------- compatibility layer (mimic parts of QTabWidget API) ----------
    def addTab(self, widget: QWidget, title: str, icon: QIcon = QIcon()) -> int:
        idx = self._tabbar.addTab(icon, title)
        self._stack.insertWidget(idx, widget)
        return idx

    def insertTab(self, index: int, widget: QWidget, title: str, icon: QIcon = QIcon()) -> int:
        self._stack.insertWidget(index, widget)
        return self._tabbar.insertTab(index, icon, title)

    def removeTab(self, index: int) -> None:
        w = self._stack.widget(index)
        if w is not None:
            self._stack.removeWidget(w)
        self._tabbar.removeTab(index)

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < self._stack.count():
            self._tabbar.setCurrentIndex(index)
            self._stack.setCurrentIndex(index)

    def currentIndex(self) -> int:
        return self._tabbar.currentIndex()

    def setCurrentWidget(self, w: QWidget) -> None:
        i = self._stack.indexOf(w)
        if i != -1:
            self.setCurrentIndex(i)

    def currentWidget(self) -> QWidget | None:
        return self._stack.currentWidget()

    def widget(self, index: int) -> QWidget | None:
        return self._stack.widget(index)

    def indexOf(self, w: QWidget) -> int:
        return self._stack.indexOf(w)

    def count(self) -> int:
        return self._stack.count()

    def setTabIcon(self, index: int, icon: QIcon) -> None:
        self._tabbar.setTabIcon(index, icon)

    def setTabText(self, index: int, text: str) -> None:
        self._tabbar.setTabText(index, text)

    def setTabToolTip(self, index: int, text: str) -> None:
        self._tabbar.setTabToolTip(index, text)

    def tabText(self, index: int) -> str:
        return self._tabbar.tabText(index)

    def tabBar(self) -> DragTabBar:
        return self._tabbar

    # Called by DragTabBar on intra-bar reordering (cross-window DnD uses tabInsertRequested)
    @Slot(int, int)
    def moveTab(self, from_index: int, to_index: int):
        if from_index == to_index:
            return
        
        # Validate source index
        if from_index < 0 or from_index >= self.count():
            return
        
        w = self._stack.widget(from_index)
        if w is None:
            return
        
        title = self._tabbar.tabText(from_index)
        icon = self._tabbar.tabIcon(from_index)

        # Remove from current position
        self._stack.removeWidget(w)
        self._tabbar.removeTab(from_index)

        # After removal, count has decreased by 1
        # to_index should already be adjusted by the caller to account for the removal
        # Clamp to valid range for insertion (0 to count, where count is the new count after removal)
        # After removal, we have count-1 tabs, so valid insertion indices are 0 to count-1
        new_count = self.count()
        to_index = max(0, min(to_index, new_count)) if new_count > 0 else 0

        # Insert at new position
        self._stack.insertWidget(to_index, w)
        self._tabbar.insertTab(to_index, icon, title)
        self.setCurrentIndex(to_index)

    # ---- selection/update fan-out -------------------------------------------

    @Slot(int)
    def handle_current_changed(self, index: int) -> None:
        if index != -1:
            view = self.web_view(index)
            if view:
                if view.url():
                    view.setFocus()
                self.title_changed.emit(view.title())
                self.load_progress.emit(view.load_progress())
                self.url_changed.emit(view.url())
                self.fav_icon_changed.emit(view.fav_icon())

                # Back/Forward/Stop/Reload states
                for act in (
                    QWebEnginePage.WebAction.Back,
                    QWebEnginePage.WebAction.Forward,
                    QWebEnginePage.WebAction.Stop,
                    QWebEnginePage.WebAction.Reload,
                ):
                    self.web_action_enabled_changed.emit(act, view.is_web_action_enabled(act))
            return

        # No current tab
        self.title_changed.emit("")
        self.load_progress.emit(0)
        self.url_changed.emit(QUrl())
        self.fav_icon_changed.emit(QIcon())
        self.web_action_enabled_changed.emit(QWebEnginePage.WebAction.Back, False)
        self.web_action_enabled_changed.emit(QWebEnginePage.WebAction.Forward, False)
        self.web_action_enabled_changed.emit(QWebEnginePage.WebAction.Stop, False)
        self.web_action_enabled_changed.emit(QWebEnginePage.WebAction.Reload, True)

    # ---- context menu on the tabbar -----------------------------------------

    @Slot(QtCore.QPoint)
    def handle_context_menu_requested(self, pos):
        menu = QMenu(self)

        act_new = menu.addAction("New &Tab")
        act_new.setShortcut(QKeySequence.AddTab)
        act_new.triggered.connect(self.create_tab)

        index = self.tabBar().tabAt(pos)
        if index != -1:
            act_clone = menu.addAction("Clone Tab")
            act_clone.triggered.connect(partial(self.clone_tab, index))
            menu.addSeparator()

            act_close = menu.addAction("Close Tab")
            act_close.setShortcut(QKeySequence.Close)
            act_close.triggered.connect(partial(self.close_tab, index))

            act_close_others = menu.addAction("Close Other Tabs")
            act_close_others.triggered.connect(partial(self.close_other_tabs, index))
            menu.addSeparator()

            act_reload = menu.addAction("Reload Tab")
            act_reload.setShortcut(QKeySequence.Refresh)
            act_reload.triggered.connect(partial(self.reload_tab, index))
        else:
            menu.addSeparator()

        menu.addAction("Reload All Tabs", self.reload_all_tabs)
        menu.exec(QCursor.pos())

    # ---- convenience getters -------------------------------------------------

    def current_web_view(self) -> WebView | None:
        return self.web_view(self.currentIndex())

    def web_view(self, index: int) -> WebView | None:
        w = self.widget(index)
        return w if isinstance(w, WebView) else None

    # ---- per-view signal fan-in ---------------------------------------------

    def _title_changed(self, web_view: WebView, title: str):
        index = self.indexOf(web_view)
        if index != -1:
            self.setTabText(index, title)
            self.setTabToolTip(index, title)
            if self.currentIndex() == index:
                self.title_changed.emit(title)

    def _url_changed(self, web_view: WebView, url: QUrl):
        index = self.indexOf(web_view)
        if index != -1:
            self.tabBar().setTabData(index, url)
            if self.currentIndex() == index:
                self.url_changed.emit(url)

    def _load_progress(self, web_view: WebView, progress: int):
        if self.currentIndex() == self.indexOf(web_view):
            self.load_progress.emit(progress)

    def _fav_icon_changed(self, web_view: WebView, icon: QIcon):
        index = self.indexOf(web_view)
        if index != -1:
            self.setTabIcon(index, icon)
            if self.currentIndex() == index:
                self.fav_icon_changed.emit(icon)

    def _link_hovered(self, web_view: WebView, url: str):
        if self.currentIndex() == self.indexOf(web_view):
            self.link_hovered.emit(url)

    def _webaction_enabled_changed(self, web_view: WebView,
                                   action: QWebEnginePage.WebAction, enabled: bool):
        if self.currentIndex() == self.indexOf(web_view):
            self.web_action_enabled_changed.emit(action, enabled)

    def _window_close_requested(self, web_view: WebView):
        index = self.indexOf(web_view)
        if web_view.page().inspectedPage():
            self.window().close()
        elif index >= 0:
            self.close_tab(index)

    def _find_text_finished(self, web_view: WebView, result: QWebEngineFindTextResult):
        if self.currentIndex() == self.indexOf(web_view):
            self.find_text_finished.emit(result)

    # ---- view creation -------------------------------------------------------

    def setup_view(self, web_view: WebView):
        web_page = web_view.page()
        web_view.titleChanged.connect(partial(self._title_changed, web_view))
        web_view.urlChanged.connect(partial(self._url_changed, web_view))
        web_view.loadProgress.connect(partial(self._load_progress, web_view))
        web_page.linkHovered.connect(partial(self._link_hovered, web_view))
        web_view.fav_icon_changed.connect(partial(self._fav_icon_changed, web_view))
        web_view.web_action_enabled_changed.connect(
            partial(self._webaction_enabled_changed, web_view)
        )
        web_page.windowCloseRequested.connect(
            partial(self._window_close_requested, web_view)
        )
        web_view.dev_tools_requested.connect(self.dev_tools_requested)
        web_page.findTextFinished.connect(
            partial(self._find_text_finished, web_view)
        )

    def create_tab(self):
        wv = self.create_background_tab()
        self.setCurrentWidget(wv)
        return wv

    def create_background_tab(self):
        web_view = WebView()
        web_page = WebPage(self._profile, web_view)
        web_view.set_page(web_page)
        self.setup_view(web_view)

        index = self.addTab(web_view, "(Untitled)")
        self.setTabIcon(index, web_view.fav_icon())

        # if title already available, seed it
        if web_view.title():
            self.setTabText(index, web_view.title())

        cur = self.currentWidget()
        if cur is not None:
            web_view.resize(cur.size())

        web_view.show()
        return web_view

    # ---- bulk ops / helpers --------------------------------------------------

    def reload_all_tabs(self):
        for i in range(self.count()):
            view = self.web_view(i)
            if view:
                view.reload()

    def close_other_tabs(self, index: int):
        for i in range(self.count() - 1, index, -1):
            self.close_tab(i)
        for i in range(index - 1, -1, -1):
            self.close_tab(i)

    def close_tab(self, index: int):
        view = self.web_view(index)
        if view:
            had_focus = view.hasFocus()
            self.removeTab(index)
            view.deleteLater()
            if had_focus and self.count() > 0:
                self.current_web_view().setFocus()
            if self.count() == 0:
                self.window().close()

    def clone_tab(self, index: int):
        view = self.web_view(index)
        if view:
            tab = self.create_tab()
            tab.setUrl(view.url())

    def set_url(self, url: QUrl | str):
        view = self.current_web_view()
        if view:
            view.setUrl(QUrl(url) if isinstance(url, str) else url)
            view.setFocus()

    def trigger_web_page_action(self, action: QWebEnginePage.WebAction):
        view = self.current_web_view()
        if view:
            view.triggerPageAction(action)
            view.setFocus()

    def next_tab(self):
        n = self.currentIndex() + 1
        if n == self.count():
            n = 0
        self.setCurrentIndex(n)

    def previous_tab(self):
        n = self.currentIndex() - 1
        if n < 0:
            n = self.count() - 1
        self.setCurrentIndex(n)

    def reload_tab(self, index: int):
        view = self.web_view(index)
        if view:
            view.reload()