# Copyright (C) 2023 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause
from __future__ import annotations

from pathlib import Path
from datetime import datetime

from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHeaderView,
                               QLabel, QListWidget, QMessageBox, QPushButton, 
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
                               QAbstractItemView, QFrame, QMenu, QProgressBar, QStyle, QWidget)
from PySide6.QtCore import Qt, QFileInfo, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter


class DownloadWidget(QFrame):
    """A widget representing a single download item in the download manager."""
    
    download_complete = Signal(int)  # Emitted when download completes
    download_cancelled = Signal(int)  # Emitted when download is cancelled
    
    def __init__(self, download_item: QWebEngineDownloadRequest, row: int, parent=None):
        super().__init__(parent)
        self._download_item = download_item
        self._row = row
        
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: #2f2f31;
                border: 1px solid #3f3f41;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # File name and icon
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        
        self._file_icon = QLabel()
        self._file_icon.setFixedSize(24, 24)
        self._file_icon.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self._file_icon)
        
        self._file_name_label = QLabel()
        self._file_name_label.setStyleSheet("""
            QLabel {
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
        """)
        self._file_name_label.setTextFormat(Qt.PlainText)
        header_layout.addWidget(self._file_name_label, 1)
        layout.addLayout(header_layout)
        
        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3f3f41;
                border-radius: 2px;
                background-color: #1a1a1a;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #0a84ff;
            }
        """)
        layout.addWidget(self._progress_bar)
        
        # Status and controls
        footer_layout = QHBoxLayout()
        
        self._status_label = QLabel()
        self._status_label.setStyleSheet("""
            QLabel {
                color: #aaa;
                font-size: 11px;
            }
        """)
        footer_layout.addWidget(self._status_label, 1)
        
        self._open_button = QPushButton("Open")
        self._open_button.setStyleSheet("""
            QPushButton {
                background-color: #0a84ff;
                color: white;
                border: none;
                padding: 4px 12px;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0c92ff;
            }
            QPushButton:pressed {
                background-color: #0972cc;
            }
        """)
        self._open_button.clicked.connect(self._open_file)
        self._open_button.hide()
        footer_layout.addWidget(self._open_button)
        
        self._open_folder_button = QPushButton("Show in Folder")
        self._open_folder_button.setStyleSheet("""
            QPushButton {
                background-color: #505053;
                color: white;
                border: none;
                padding: 4px 12px;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #606063;
            }
            QPushButton:pressed {
                background-color: #404043;
            }
        """)
        self._open_folder_button.clicked.connect(self._open_folder)
        self._open_folder_button.hide()
        footer_layout.addWidget(self._open_folder_button)
        
        layout.addLayout(footer_layout)
        
        # Update display
        self._update_display()
        
        # Connect signals
        self._download_item.totalBytesChanged.connect(self._update_display)
        self._download_item.receivedBytesChanged.connect(self._update_display)
        self._download_item.stateChanged.connect(self._update_display)
        
    def _update_display(self):
        """Update the display based on download state."""
        # Set file name
        suggested_filename = self._download_item.downloadFileName()
        if suggested_filename:
            self._file_name_label.setText(suggested_filename)
        else:
            self._file_name_label.setText("Downloading...")
        
        # Set icon (simple file icon)
        icon = self.style().standardIcon(QStyle.SP_FileIcon)
        pixmap = icon.pixmap(24, 24)
        self._file_icon.setPixmap(pixmap)
        
        # Update progress
        total = self._download_item.totalBytes()
        received = self._download_item.receivedBytes()
        
        state = self._download_item.state()
        
        if state == QWebEngineDownloadRequest.DownloadInProgress:
            if total > 0:
                progress = int((received / total) * 100)
                self._progress_bar.setValue(progress)
                self._status_label.setText(f"Downloading... {self._format_bytes(received)} / {self._format_bytes(total)}")
            else:
                self._progress_bar.setValue(0)
                self._status_label.setText(f"Downloading... {self._format_bytes(received)}")
        elif state == QWebEngineDownloadRequest.DownloadCompleted:
            self._progress_bar.setValue(100)
            self._status_label.setText("Completed")
            self._open_button.show()
            self._open_folder_button.show()
            self.download_complete.emit(self._row)
        elif state == QWebEngineDownloadRequest.DownloadCancelled:
            self._status_label.setText("Cancelled")
            self.download_cancelled.emit(self._row)
        elif state == QWebEngineDownloadRequest.DownloadInterrupted:
            self._status_label.setText("Interrupted")
    
    def _format_bytes(self, bytes: int) -> str:
        """Format bytes into human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024.0:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.1f} TB"
    
    @Slot()
    def _open_file(self):
        """Open the downloaded file."""
        url = QUrl.fromLocalFile(self._download_item.downloadDirectory() + "/" + self._download_item.downloadFileName())
        if url.isValid():
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)
    
    @Slot()
    def _open_folder(self):
        """Open the folder containing the downloaded file."""
        url = QUrl.fromLocalFile(self._download_item.downloadDirectory())
        if url.isValid():
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)
    
    def cancel(self):
        """Cancel the download."""
        self._download_item.cancel()


class DownloadManager(QDialog):
    """Download manager dialog showing all active and completed downloads."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downloads")
        self.setMinimumSize(600, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        self._downloads = []
        self._force_close = False
        
        self.setStyleSheet("""
            QDialog {
                background-color: #252526;
            }
            QLabel {
                color: white;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Title
        title_label = QLabel("Downloads")
        title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 4px 0px;
            }
        """)
        layout.addWidget(title_label)
        
        # Scroll area for downloads
        from PySide6.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #3f3f41;
                border-radius: 4px;
                background-color: #2b2b2b;
            }
        """)
        
        self._downloads_widget = QWidget()
        self._downloads_layout = QVBoxLayout(self._downloads_widget)
        self._downloads_layout.setContentsMargins(8, 8, 8, 8)
        self._downloads_layout.setSpacing(8)
        self._downloads_layout.addStretch()
        
        scroll_area.setWidget(self._downloads_widget)
        layout.addWidget(scroll_area, 1)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        self._clear_button = QPushButton("Clear Completed")
        self._clear_button.setStyleSheet("""
            QPushButton {
                background-color: #505053;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #606063;
            }
            QPushButton:pressed {
                background-color: #404043;
            }
        """)
        self._clear_button.clicked.connect(self._clear_completed)
        button_layout.addWidget(self._clear_button)
        
        button_layout.addStretch()
        
        self._close_button = QPushButton("Close")
        self._close_button.setStyleSheet("""
            QPushButton {
                background-color: #0a84ff;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0c92ff;
            }
            QPushButton:pressed {
                background-color: #0972cc;
            }
        """)
        self._close_button.clicked.connect(self.accept)
        button_layout.addWidget(self._close_button)
        
        layout.addLayout(button_layout)
        
        # Empty state
        self._empty_label = QLabel("No downloads")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 14px;
                padding: 40px;
            }
        """)
        self._empty_label.hide()
        self._downloads_layout.insertWidget(0, self._empty_label)
    
    def add_download(self, download_item: QWebEngineDownloadRequest):
        """Add a new download to the manager."""
        # Check if already exists
        for dw in self._downloads:
            if dw._download_item == download_item:
                return
        
        row = len(self._downloads)
        download_widget = DownloadWidget(download_item, row, self._downloads_widget)
        self._downloads.append(download_widget)
        
        # Insert before the stretch spacer
        self._downloads_layout.insertWidget(self._downloads_layout.count() - 1, download_widget)
        
        # Connect signals
        download_widget.download_complete.connect(self._on_download_complete)
        download_widget.download_cancelled.connect(self._on_download_cancelled)
        
        # Hide empty label
        self._empty_label.hide()
        
        # Show the dialog if not already visible
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()
    
    def _on_download_complete(self, row: int):
        """Handle download completion."""
        # Could add notification or other handling here
        pass
    
    def _on_download_cancelled(self, row: int):
        """Handle download cancellation."""
        # Could add notification or other handling here
        pass
    
    @Slot()
    def _clear_completed(self):
        """Clear completed downloads."""
        to_remove = []
        for i, dw in enumerate(self._downloads):
            if dw._download_item.state() == QWebEngineDownloadRequest.DownloadCompleted:
                to_remove.append((i, dw))
        
        # Remove from back to front to maintain indices
        for i, dw in reversed(to_remove):
            self._downloads.remove(dw)
            dw.setParent(None)
            dw.deleteLater()
        
        if not self._downloads:
            self._empty_label.show()
    
    def closeEvent(self, event):
        """Handle close event - hide instead of close, unless force_close is True."""
        if self._force_close:
            event.accept()
        else:
            event.ignore()
            self.hide()
    
    def force_close(self):
        """Force close the download manager (used when all browser windows are closed)."""
        self._force_close = True
        self.close()
    
    def showEvent(self, event):
        """Handle show event."""
        super().showEvent(event)
        if not self._downloads:
            self._empty_label.show()

