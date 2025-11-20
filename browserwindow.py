# Copyright (C) 2023 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause
from __future__ import annotations

import sys

from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import (QMainWindow, QFileDialog, QStyle, QHBoxLayout,
                               QInputDialog, QLineEdit, QMessageBox, QToolButton,
                               QProgressBar, QToolBar, QVBoxLayout, QWidget, QPushButton, QLabel)
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtCore import QUrl, Qt, Slot, Signal, QPoint, QTimer
from PySide6 import QtCore, QtGui, QtWidgets

from tabwidget import TabWidget
from protectedurlbar import ProtectedUrlBar

def remove_backspace(keys):
    result = keys.copy()
    # Chromium already handles navigate on backspace when appropriate.
    for i, key in enumerate(result):
        if (key[0].key() & Qt.Key.Key_unknown) == Qt.Key.Key_Backspace:
            del result[i]
            break
    return result

class BrowserWindow(QMainWindow):

    def __init__(self, browser, profile, forDevTools, url, title, app_icon):
        super().__init__()
        self._browser = browser
        self._profile = profile
        self._home_url = url
        self._home_icon = app_icon
        self._window_title = title
        self._last_search = ""
        self._drag_seq_counter = 0
        self._drag_seq_accepted = -1
        self._history_back_action = None
        self._history_forward_action = None
        self._stop_reload_action = None
        self._home_action = None
        self._url_bar = None
        self._status_label = None

        # --- UI setup ---
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        # --- Actions ---
        # Use bundled minimalist SVG icons
        self._stop_icon = QIcon(":/close-x.svg")
        self._reload_icon = QIcon(":/refresh.svg")

        if not forDevTools:
            # Back
            self._history_back_action = QAction(self)
            back_shortcuts = remove_backspace(QKeySequence.keyBindings(QKeySequence.StandardKey.Back))
            back_shortcuts.append(QKeySequence(Qt.Key.Key_Back))
            self._history_back_action.setShortcuts(back_shortcuts)
            self._history_back_action.setIcon(QIcon(":/back.svg"))
            self._history_back_action.setToolTip("Go back in history")
            self._history_back_action.triggered.connect(self._back)

            # Forward
            self._history_forward_action = QAction(self)
            fwd_shortcuts = remove_backspace(QKeySequence.keyBindings(QKeySequence.StandardKey.Forward))
            fwd_shortcuts.append(QKeySequence(Qt.Key.Key_Forward))
            self._history_forward_action.setShortcuts(fwd_shortcuts)
            self._history_forward_action.setIcon(QIcon(":/forward.svg"))
            self._history_forward_action.setToolTip("Go forward in history")
            self._history_forward_action.triggered.connect(self._forward)

            # Stop / Reload
            self._stop_reload_action = QAction(self)
            self._stop_reload_action.setIcon(self._reload_icon)
            self._stop_reload_action.setToolTip("Reload the current page")
            self._stop_reload_action.triggered.connect(self._stop_reload)

            # Download manager
            self._downloads_action = QAction(self)
            self._downloads_action.setIcon(QIcon(":/downloads.svg"))
            self._downloads_action.setToolTip("Show downloads")
            self._downloads_action.triggered.connect(self._show_downloads)

            # Home
            self._home_action = QAction(self)
            self._home_action.setIcon(self._home_icon)
            self._home_action.setToolTip("Go Home")
            self._home_action.triggered.connect(self._go_home)

            # Zoom shortcuts (no buttons)
            for seq, func in [
                (QKeySequence(Qt.CTRL | Qt.Key_Plus), self._zoom_in),
                (QKeySequence(Qt.CTRL | Qt.Key_Minus), self._zoom_out),
                (QKeySequence(Qt.CTRL | Qt.Key_0), self._reset_zoom),
            ]:
                a = QAction(self)
                a.setShortcut(seq)
                a.triggered.connect(func)
                self.addAction(a)

        # --- Layout ---
        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tab_widget = TabWidget(profile, self)
        
        # Create status label for hover URL display
        self._status_label = QLabel(self)
        self._status_label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 200);
                color: white;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 11px;
                font-family: monospace;
            }
        """)
        self._status_label.hide()
        self._status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._status_label.setWordWrap(False)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        # Make sure label is on top of other widgets
        self._status_label.raise_()

        # --- Custom top bar ---
        if not forDevTools:
            self._top_bar = self._build_top_bar()
            layout.addWidget(self._top_bar)

        # --- Navigation bar ---
        if not forDevTools:
            self._nav_bar = self._build_nav_bar()
            layout.addWidget(self._nav_bar)

        # --- Progress bar (thin line) ---
        if not forDevTools:
            self._progress_bar = QProgressBar(self)
            self._progress_bar.setMaximumHeight(1)
            self._progress_bar.setTextVisible(False)
            self._progress_bar.setStyleSheet(
                "QProgressBar {border: 0px} QProgressBar::chunk {background-color: #da4453}"
            )
            layout.addWidget(self._progress_bar)
        
        self.setCentralWidget(central_widget)

        # fullscreen restore helpers
        self._pre_fs_geometry = None
        
        if not forDevTools:
            # --- Connect tab events ---
            self._tab_widget.title_changed.connect(self.handle_web_view_title_changed)
            self._tab_widget.load_progress.connect(self.handle_web_view_load_progress)
            self._tab_widget.web_action_enabled_changed.connect(self.handle_web_action_enabled_changed)
            self._tab_widget.dev_tools_requested.connect(self.handle_dev_tools_requested)
            self._tab_widget.link_hovered.connect(self.handle_link_hovered)
            # --- Connect URL bar signals (after _url_bar is created in _build_nav_bar) ---
            if self._url_bar:
                self._url_bar.urlEntered.connect(self._navigate_from_url_bar)
            self._tab_widget.url_changed.connect(self._url_from_tab)

        layout.addWidget(self._tab_widget, 1)
        # --- Create initial tab ---
        self.handle_web_view_title_changed("")
        
        # Timer to hide status label when not hovering (only for non-DevTools windows)
        if not forDevTools:
            self._status_hide_timer = QTimer(self)
            self._status_hide_timer.setSingleShot(True)
            self._status_hide_timer.timeout.connect(self._hide_status_label)
        else:
            self._status_hide_timer = None

    def new_drag_seq(self) -> int:
        self._drag_seq_counter += 1
        return self._drag_seq_counter

    def mark_drag_seq_accepted(self, seq: int):
        self._drag_seq_accepted = seq

    def was_drag_seq_accepted(self, seq: int) -> bool:
        return self._drag_seq_accepted == seq

    def detach_tab_to_new_window(self, from_index: int, global_pos: QtCore.QPoint):
        # If only one tab, just move this window instead of spawning a new one
        if self._tab_widget.count() == 1:
            target = global_pos - QtCore.QPoint(60, 20)
            self.move(target)
            self.raise_()
            self.activateWindow()
            return

        view = self._tab_widget.web_view(from_index)
        txt = self._tab_widget.tabText(from_index)
        has_focus = view.hasFocus()
        self._tab_widget.removeTab(from_index)
        if has_focus and self._tab_widget.count() > 0:
            self._tab_widget.current_web_view().setFocus()

        # Create a new BrowserWindow via Browser and insert the detached view
        child = self._browser.create_hidden_window()
        child._tab_widget.addTab(view, txt, view.fav_icon())
        child.move(global_pos - QtCore.QPoint(60, 20))
        child.show()


    def receive_tab_from(self, src_window: "BrowserWindow", src_index: int, dst_index: int):
        view = src_window._tab_widget.web_view(src_index)
        if view is None:
            return
        txt = src_window._tab_widget.tabText(src_index)
        has_focus = view.hasFocus()
        
        # Remove from source window first
        src_window._tab_widget.removeTab(src_index)
        
        # Validate destination index
        dst_index = max(0, min(dst_index, self._tab_widget.count()))
        
        # Insert into destination window
        self._tab_widget.insertTab(dst_index, view, txt, view.fav_icon())
        
        # Set the inserted tab as current and ensure it's visible
        self._tab_widget.setCurrentIndex(dst_index)
        view.show()
        
        # Set focus if it had focus before
        if has_focus:
            view.setFocus()
        elif self._tab_widget.count() > 0:
            # Otherwise focus the current tab
            current_view = self._tab_widget.current_web_view()
            if current_view:
                current_view.setFocus()

        if src_window._tab_widget.count() == 0:
            src_window.close()


    def take_tab(self, index: int):
        w = self._tab_widget.widget(index)
        title = self._tab_widget.tabText(index)

        self._tab_widget.removeTab(index)
        return w, title

    def insert_tab(self, widget: QtWidgets.QWidget, title: str, index: int | None = None):
        self._tab_widget.insert_tab(self, index, view)
        
    def closeEvent(self, event: QtGui.QCloseEvent):
        # Always remove from Browser list
        try:
            self._browser.windows().remove(self)
        except ValueError:
            pass
        
        # Close download manager if it's the last window
        if not self._browser.windows() and self._browser.download_manager():
            self._browser.download_manager().force_close()
        
        super().closeEvent(event)

    def _go_home(self):
        self._tab_widget.set_url(self._home_url)
    
    @Slot()
    def _show_downloads(self):
        """Show the download manager dialog."""
        download_manager = self._browser.download_manager()
        download_manager.show()
        download_manager.raise_()
        download_manager.activateWindow()

    @Slot(str)
    def _navigate_from_url_bar(self, url_string: str):
        """Handle navigation from URL bar (Enter pressed or similar)."""
        self._tab_widget.set_url(url_string)

    @Slot(QUrl)
    def _url_from_tab(self, url: QUrl):
        """Update URL bar when tab's URL changes."""
        # Hide status label when URL changes (tab switch or navigation)
        if self._status_label:
            self._status_label.hide()
            if self._status_hide_timer:
                self._status_hide_timer.stop()
        
        if self._url_bar:
            # Ignore about:blank to avoid overwriting the initial URL bar state
            if url.toString() != "about:blank":
                self._url_bar.set_full(url, lock_to_origin=True)

    @Slot()
    def _new_tab(self):
        self._tab_widget.create_tab()
        self._tab_widget.set_url(self._home_url)

    @Slot()
    def _close_current_tab(self):
        self._tab_widget.close_tab(self._tab_widget.currentIndex()) 

    def sizeHint(self):
        desktop_rect = QGuiApplication.primaryScreen().geometry()
        return desktop_rect.size() * 0.9

    @Slot()
    def _find_next(self):
        tab = self.current_tab()
        if tab and self._last_search:
            tab.findText(self._last_search)

    @Slot()
    def _find_previous(self):
        tab = self.current_tab()
        if tab and self._last_search:
            tab.findText(self._last_search, QWebEnginePage.FindBackward)

    @Slot()
    def _stop(self):
        self._tab_widget.trigger_web_page_action(QWebEnginePage.Stop)

    @Slot()
    def _reload(self):
        self._tab_widget.trigger_web_page_action(QWebEnginePage.Reload)

    @Slot()
    def _zoom_in(self):
        tab = self.current_tab()
        if tab:
            tab.setZoomFactor(tab.zoomFactor() + 0.1)

    @Slot()
    def _zoom_out(self):
        tab = self.current_tab()
        if tab:
            tab.setZoomFactor(tab.zoomFactor() - 0.1)

    @Slot()
    def _reset_zoom(self):
        tab = self.current_tab()
        if tab:
            tab.setZoomFactor(1)

    @Slot()
    def _emit_dev_tools_requested(self):
        tab = self.current_tab()
        if tab:
            tab.dev_tools_requested.emit(tab.page())

    @Slot()
    def _back(self):
        self._tab_widget.trigger_web_page_action(QWebEnginePage.WebAction.Back)

    @Slot()
    def _forward(self):
        self._tab_widget.trigger_web_page_action(QWebEnginePage.WebAction.Forward)

    @Slot()
    def _stop_reload(self):
        a = self._stop_reload_action.data()
        self._tab_widget.trigger_web_page_action(QWebEnginePage.WebAction(a))

    def _build_top_bar(self):
        top_bar = QWidget(self)
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(30)
        top_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_bar.setStyleSheet("""
            QWidget#topBar {
                background-color: #2b2b2b;
            }
        """)

        layout = QHBoxLayout(top_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._tab_widget._tabbar, 1)

        controls_widget = self._build_window_controls()
        layout.addWidget(controls_widget, 0, Qt.AlignRight)

        self._top_bar = top_bar  # for DragTabBar references

        return top_bar
    
    def _build_window_controls(self):
        """Build minimize, maximize, and close buttons."""
        controls = QWidget(self)
        controls.setFixedHeight(30)
        controls.setStyleSheet("background-color: transparent; border-bottom: 2px solid #1a1a1a;")
        
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        def make_control_btn(icon_char, tooltip, handler):
            btn = QPushButton(icon_char, controls)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tooltip)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: #ffffff;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                }
                QPushButton:pressed {
                    background-color: rgba(255, 255, 255, 0.2);
                }
            """)
            btn.clicked.connect(handler)
            return btn
        
        # Minimize button (using unicode symbol)
        minimize_btn = make_control_btn("−", "Minimize", self._minimize_window)
        layout.addWidget(minimize_btn)
        
        # Maximize/Restore button
        self._maximize_btn = make_control_btn("□", "Maximize", self._toggle_maximize)
        layout.addWidget(self._maximize_btn)
        
        # Close button
        close_btn = make_control_btn("×", "Close", self.close)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e81123;
            }
            QPushButton:pressed {
                background-color: #c50e1f;
            }
        """)
        layout.addWidget(close_btn)
        
        return controls
    
    def _is_localhost_or_network(self, url):
        """Check if URL is localhost or a network address (not a regular web URL)."""
        if isinstance(url, str):
            # Check if it looks like localhost or an IP address
            if url in ("localhost", "127.0.0.1", "::1"):
                return True
            # Check for localhost URLs
            if "localhost" in url.lower() or "127.0.0.1" in url:
                return True
            # Check for IP addresses
            if url.replace(".", "").replace(":", "").isdigit():
                return True
            return False
        elif isinstance(url, QUrl):
            # Check QUrl host
            host = url.host()
            if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.") or host.startswith("192.168") or host.startswith("10."):
                return True
            return False
        return False
    
    def _build_nav_bar(self):
        """Build navigation bar with back/forward/refresh/home buttons."""
        nav_bar = QWidget(self)
        nav_bar.setObjectName("navBar")
        
        # Check if we should show the URL bar (only for localhost/network URLs)
        show_url_bar = self._is_localhost_or_network(self._home_url)
        
        # Adjust height based on whether URL bar is shown
        nav_bar_height = 40 if show_url_bar else 30
        nav_bar.setFixedHeight(nav_bar_height)
        
        nav_bar.setStyleSheet("""
            QWidget#navBar {
                background-color: #4a4a4d;
            }
        """)
        
        layout = QHBoxLayout(nav_bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(16)

        def make_btn(action):
            btn = QToolButton(nav_bar)
            btn.setAutoRaise(True)
            btn.setDefaultAction(action)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            if action == self._stop_reload_action:
                btn.setIconSize(QtCore.QSize(24, 24))
            elif action == self._downloads_action or action == self._home_action:
                btn.setIconSize(QtCore.QSize(20, 20))
            else:
                btn.setIconSize(QtCore.QSize(18, 18))
            btn.setStyleSheet("""
                QToolButton {
                    background-color: transparent;
                    border: none;
                }
                QToolButton:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                }
                QToolButton:disabled {
                    opacity: 0.3;
                }
            """)
            return btn

        for action in (
            self._history_back_action,
            self._history_forward_action,
            self._stop_reload_action,
            self._home_action,
        ):
            layout.addWidget(make_btn(action))
        
        # Only add URL bar for localhost/network URLs
        if show_url_bar:
            self._url_bar = ProtectedUrlBar(self)
            self._url_bar.set_full(self._home_url)
            layout.addWidget(self._url_bar)
        else:
            self._url_bar = None
        
        # Add stretch to push home/downloads buttons to the right
        layout.addStretch()
        
        # Downloads button (on the right)
        layout.addWidget(make_btn(self._downloads_action))
        
        return nav_bar
    
    def _minimize_window(self):
        """Minimize the window."""
        self.showMinimized()
    
    def _toggle_maximize(self):
        """Toggle maximize/restore window."""
        if self.isMaximized():
            self.showNormal()
            self._maximize_btn.setText("□")
            self._maximize_btn.setToolTip("Maximize")
        else:
            self.showMaximized()
            self._maximize_btn.setText("❐")  # Restore icon
            self._maximize_btn.setToolTip("Restore")


    def handle_web_action_enabled_changed(self, action, enabled):
        if action == QWebEnginePage.WebAction.Back:
            self._history_back_action.setEnabled(enabled)
        elif action == QWebEnginePage.WebAction.Forward:
            self._history_forward_action.setEnabled(enabled)
        elif action == QWebEnginePage.WebAction.Reload:
            return
        elif action == QWebEnginePage.WebAction.Stop:
            return
        else:
            print("Unhandled webActionChanged signal", file=sys.stderr)

    def handle_web_view_title_changed(self, title):
        off_the_record = self._profile.isOffTheRecord()
        suffix = self._window_title
        if title:
            self.setWindowTitle(f"{title} - {suffix}")
        else:
            self.setWindowTitle(suffix)

    def handle_new_window_triggered(self):
        window = self._browser.create_window()

    def handle_file_open_triggered(self):
        filter = "Web Resources (*.html *.htm *.svg *.png *.gif *.svgz);;All files (*.*)"
        url, _ = QFileDialog.getOpenFileUrl(self, "Open Web Resource", "", filter)
        if url:
            self.current_tab().setUrl(url)

    def handle_find_action_triggered(self):
        if not self.current_tab():
            return
        search, ok = QInputDialog.getText(self, "Find", "Find:",
                                          QLineEdit.EchoMode.Normal, self._last_search)
        if ok and search:
            self._last_search = search
            self.current_tab().findText(self._last_search)        

    def tab_widget(self):
        return self._tab_widget

    def current_tab(self):
        return self._tab_widget.current_web_view()

    def handle_web_view_load_progress(self, progress):
        if 0 < progress and progress < 100:
            self._stop_reload_action.setData(QWebEnginePage.WebAction.Stop)
            self._stop_reload_action.setIcon(self._stop_icon)
            self._stop_reload_action.setToolTip("Stop loading the current page")
            self._progress_bar.setValue(progress)
        else:
            self._stop_reload_action.setData(QWebEnginePage.WebAction.Reload)
            self._stop_reload_action.setIcon(self._reload_icon)
            self._stop_reload_action.setToolTip("Reload the current page")
            self._progress_bar.setValue(0)

    def handle_show_window_triggered(self):
        action = self.sender()
        if action:
            offset = action.data()
            window = self._browser.windows()[offset]
            window.activateWindow()
            window.current_tab().setFocus()

    def handle_dev_tools_requested(self, source):
        page = self._browser.create_dev_tools_window().current_tab().page()
        source.setDevToolsPage(page)
        source.triggerAction(QWebEnginePage.WebAction.InspectElement)

    def browser(self):
        return self._browser

    @Slot(str)
    def handle_link_hovered(self, url: str):
        """Handle link hover events to display URL in status label."""
        if not self._status_label:
            return
            
        if url:
            # Show and update the status label
            self._status_label.setText(url)
            self._status_label.adjustSize()
            self._update_status_label_position()
            self._status_label.show()
            self._status_label.raise_()
            # Reset the hide timer
            if self._status_hide_timer:
                self._status_hide_timer.stop()
        else:
            # Empty URL means mouse left the link - start timer to hide
            if self._status_hide_timer:
                self._status_hide_timer.start(300)  # Hide after 300ms
    
    def _hide_status_label(self):
        """Hide the status label."""
        if self._status_label:
            self._status_label.hide()
    
    def _update_status_label_position(self):
        """Update the position of the status label to bottom left of webview area."""
        if not self._status_label:
            return
        
        # Get the tab widget's geometry relative to the window
        tab_widget_rect = self._tab_widget.geometry()
        
        # Get the tab widget's position relative to the parent (central widget or window)
        tab_pos = self._tab_widget.mapTo(self, QPoint(0, 0))
        
        # Calculate position: bottom left with some margin
        margin = 8
        x = tab_pos.x() + margin
        y = tab_pos.y() + tab_widget_rect.height() - self._status_label.height() - margin
        
        self._status_label.move(x, y)
    
    def resizeEvent(self, event):
        """Handle window resize to reposition status label."""
        super().resizeEvent(event)
        if self._status_label and self._status_label.isVisible():
            self._update_status_label_position()
    
    def showEvent(self, event):
        """Handle window show to ensure status label position is correct."""
        super().showEvent(event)
        if self._status_label and self._status_label.isVisible():
            # Update position after window is shown
            QTimer.singleShot(0, self._update_status_label_position)

    # --- Fullscreen control (invoked by WebView on page requests) ---
    def enter_fullscreen(self):
        if not self.isFullScreen():
            self._pre_fs_geometry = self.geometry()
            # Hide UI elements for fullscreen
            if hasattr(self, '_top_bar') and self._top_bar:
                self._top_bar.hide()
            if hasattr(self, '_nav_bar') and self._nav_bar:
                self._nav_bar.hide()
            if hasattr(self, '_progress_bar') and self._progress_bar:
                self._progress_bar.hide()
            self.showFullScreen()

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            # Show UI elements again
            if hasattr(self, '_top_bar') and self._top_bar:
                self._top_bar.show()
            if hasattr(self, '_nav_bar') and self._nav_bar:
                self._nav_bar.show()
            if hasattr(self, '_progress_bar') and self._progress_bar:
                self._progress_bar.show()
            if self._pre_fs_geometry is not None:
                self.setGeometry(self._pre_fs_geometry)
                self._pre_fs_geometry = None
