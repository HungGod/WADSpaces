# Copyright (C) 2023 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause
from __future__ import annotations

from PySide6.QtWebEngineCore import (qWebEngineChromiumVersion,
                                     QWebEngineProfile, QWebEngineSettings,
                                     QWebEngineDownloadRequest)
from PySide6.QtCore import QObject, Qt, Slot, QCoreApplication, QSettings
from pathlib import Path

import shutil

from downloadmanager import DownloadManager
from browserwindow import BrowserWindow

MAX_CACHE_SIZE_MB = 500

class Browser(QObject):

    def __init__(self, url, title, app_icon, parent=None):
        super().__init__(parent)
        self._windows = []
        self._profile = None
        self._url = url
        self._title = title
        self._app_icon = app_icon
        self._download_manager = None

    def create_hidden_window(self):
        is_not_url_redirect = self._title != "URL Redirect"
        if not self._profile and is_not_url_redirect:
            name = QCoreApplication.organizationName() + '.' + QCoreApplication.applicationName()
            self._profile = QWebEngineProfile(name)
            s = self._profile.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
            s.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            
            base_dir = Path.home() / ".minibrowser"
            base_dir.mkdir(parents=True, exist_ok=True)
 
            self._profile.setHttpAcceptLanguage("en-US,en;q=0.9")
            self._profile.setSpellCheckEnabled(True)
            self._profile.setSpellCheckLanguages(["en-US"])

            # Use per-app cache and storage directories to avoid cross-profile conflicts
            cache_dir = base_dir / self._title / "cache"
            stor_dir = base_dir / self._title / "storage"

            cache_dir.mkdir(parents=True, exist_ok=True)
            stor_dir.mkdir(parents=True, exist_ok=True)

            self._profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            self._profile.setCachePath(str(cache_dir))
            self._profile.setHttpCacheMaximumSize(MAX_CACHE_SIZE_MB * 1024 * 1024)
            self._profile.setPersistentStoragePath(str(stor_dir))
            self._profile.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
            
            # Set up download directory
            download_dir = base_dir / self._title / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            self._download_dir = str(download_dir)
            
            # Connect download signal
            self._profile.downloadRequested.connect(self._handle_download_requested)

        profile = self._profile if is_not_url_redirect else QWebEngineProfile.defaultProfile()

        title = QCoreApplication.organizationName() + ' - ' + QCoreApplication.applicationName()
        main_window = BrowserWindow(self, profile, False, self._url, title, self._app_icon)
        self._windows.append(main_window)
        return main_window

    def create_window(self):
        main_window = self.create_hidden_window()
        main_window._tab_widget.create_tab()
        main_window._tab_widget.set_url(self._url)
        main_window.show()
        return main_window

    def create_dev_tools_window(self):
        profile = self._profile
        main_window = BrowserWindow(self, profile, True, self._url, self._title, self._app_icon)
        self._windows.append(main_window)
        main_window._tab_widget.create_tab()
        main_window.show()
        return main_window

    def windows(self):
        return self._windows

    def lookup_window(self, index: int):
        try:
            return self._windows[index]
        except (IndexError, TypeError):
            return None

    def download_manager(self):
        """Get or create the download manager dialog."""
        if self._download_manager is None:
            self._download_manager = DownloadManager()
        return self._download_manager

    @Slot()
    def _remove_window(self):
        w = self.sender()
        if w in self._windows:
            del self._windows[self._windows.index(w)]
        # Close download manager if it's the last window
        if not self._windows and self._download_manager:
            self._download_manager.force_close()
    
    @Slot(QWebEngineDownloadRequest)
    def _handle_download_requested(self, download_item: QWebEngineDownloadRequest):
        """Handle a download request from the web engine."""
        import os
        from PySide6.QtCore import QStandardPaths
        
        # Get suggested filename
        suggested_filename = download_item.downloadFileName()
        if not suggested_filename:
            suggested_filename = "download"
        
        # Set download path
        download_path = os.path.join(self._download_dir, suggested_filename)
        download_item.setDownloadDirectory(self._download_dir)
        download_item.setDownloadFileName(suggested_filename)
        
        # Accept the download (allow it to proceed)
        download_item.accept()
        
        # Add to download manager
        download_manager = self.download_manager()
        download_manager.add_download(download_item)
