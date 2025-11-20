# protected_urlbar.py
from PySide6.QtCore import Qt, Signal, QEvent, QUrl, QPoint
from PySide6.QtGui import QKeySequence, QGuiApplication, QClipboard
from PySide6.QtWidgets import (
    QLineEdit, QSizePolicy, QApplication, QMenu
)

class ProtectedUrlBar(QLineEdit):
    urlEntered = Signal(str)        # emits full URL string
    textChangedFull = Signal(str)   # emits on any edit (full URL)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_end_pos = 0  # Position where the protected base URL ends
        
        self.setObjectName("ProtectedUrlBar")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(32)  # Fixed height to prevent text cutoff
        self.setPlaceholderText("type path…")
        self.returnPressed.connect(self._on_return)
        self.textChanged.connect(self._on_text_changed)
        self.installEventFilter(self)
        
        # Enable context menu for copying
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        
        # simple styling
        self.setStyleSheet("""
        QLineEdit#ProtectedUrlBar {
            background: #2b2b2b;
            border: 1px solid #3a3a3a;
            border-radius: 6px;
            color: #eee;
            padding: 4px 8px;
            selection-background-color: #4a6cf7;
        }
        """)

    # ---- Public API ---------------------------------------------------------

    def set_base(self, base: str | QUrl):
        """Set the protected, non-editable prefix (e.g. 'https://reddit.com/')."""
        if isinstance(base, QUrl):
            base = base.toString(QUrl.RemoveQuery | QUrl.RemoveFragment)
            if not base.endswith("/"):
                base += "/"
        
        # Update the full text and set the protected position
        current_full = self.text()
        if current_full.startswith(base):
            # If current text starts with base, keep it
            self._base_end_pos = len(base)
        else:
            # Otherwise, set to base only
            self.blockSignals(True)
            self.setText(base)
            self._base_end_pos = len(base)
            self.blockSignals(False)
            self._on_text_changed(base)

    def set_suffix(self, suffix: str):
        """Set the editable tail (e.g. 'r/all')."""
        base = self.text()[:self._base_end_pos] if self._base_end_pos > 0 else ""
        full = base + suffix
        self.blockSignals(True)
        self.setText(full)
        self._base_end_pos = len(base)
        self.blockSignals(False)
        self._on_text_changed(full)

    def full(self) -> str:
        text = self.text()
        base = text[:self._base_end_pos] if self._base_end_pos > 0 else ""
        suffix = text[self._base_end_pos:] if self._base_end_pos < len(text) else ""
        
        # If suffix starts with ':', it's a port - insert it before the trailing '/' in base
        if suffix.startswith(":"):
            # Remove trailing '/' from base if present, then add port
            if base.endswith("/"):
                base = base[:-1]
            return base + suffix
        else:
            # Normal case: base + suffix
            return text

    def set_full(self, url: str | QUrl, lock_to_origin=True):
        """Convenience: parse a full URL and split into base + suffix.
           lock_to_origin=True keeps scheme+host(+port) as base.
        """
        # Handle plain strings (like "localhost", "127.0.0.1", etc.)
        if isinstance(url, str):
            # Check if it looks like a bare hostname/IP without scheme
            if not url.startswith(("http://", "https://", "file://", "about:", "chrome:")):
                url = "http://" + url
            u = QUrl(url)
        else:
            u = url
            
        if not u.isValid() or u.isEmpty():
            self.setText("")
            self._base_end_pos = 0
            return
            
        if lock_to_origin:
            # For localhost/IP addresses without scheme, reconstruct properly
            host = u.host()
            if host and not u.scheme():
                origin = "http://" + host
            elif host:
                origin = u.scheme() + "://" + host
            else:
                # No host (e.g., about:blank) - just use the toString() as-is
                # For URLs without hosts, the full URL is the base
                full = u.toString()
                self.blockSignals(True)
                self.setText(full)
                self._base_end_pos = len(full)
                self.blockSignals(False)
                self._on_text_changed(full)
                return
            
            # For localhost/network addresses, keep port in suffix (editable) instead of base
            # Check if this is a localhost or network address based on host
            is_localhost_or_network = (host in ("localhost", "127.0.0.1", "::1") or 
                                      (host and (host.startswith("127.") or 
                                                 host.startswith("192.168") or 
                                                 host.startswith("10."))))
            
            port_suffix = ""
            if u.port() > 0 and u.port() not in (80, 443):
                if is_localhost_or_network:
                    # Keep port in suffix for localhost/network addresses
                    port_suffix = f":{u.port()}"
                else:
                    # Include port in base for regular web URLs
                    origin += f":{u.port()}"
            
            if origin and not origin.endswith("/"):
                origin += "/"
            
            suffix = u.path().lstrip("/") + port_suffix
            full = origin + suffix
            self.blockSignals(True)
            self.setText(full)
            self._base_end_pos = len(origin)
            self.blockSignals(False)
            self._on_text_changed(full)
        else:
            # treat everything up to last slash as base
            s = u.toString(QUrl.RemoveQuery | QUrl.RemoveFragment)
            if "/" in s[8:]:
                i = s.rfind("/") + 1
                base = s[:i]
                suffix = s[i:]
            else:
                base = s + "/"
                suffix = ""
            full = base + suffix
            self.blockSignals(True)
            self.setText(full)
            self._base_end_pos = len(base)
            self.blockSignals(False)
            self._on_text_changed(full)

    # ---- Behavior tweaks for a Chrome feel ---------------------------------

    def eventFilter(self, obj, ev):
        if obj is self and ev.type() == QEvent.KeyPress:
            key = ev.key()
            mods = ev.modifiers()

            # Handle Delete/Backspace at the protected boundary
            if key == Qt.Key_Backspace:
                # Check if there's a selection that crosses the protected boundary
                if self.hasSelectedText():
                    start = min(self.selectionStart(), self.selectionEnd())
                    end = max(self.selectionStart(), self.selectionEnd())
                    # If selection includes any protected text, adjust or block deletion
                    if start < self._base_end_pos:
                        # Selection starts in protected area
                        if end <= self._base_end_pos:
                            # Entire selection is in protected area, block deletion
                            return True
                        else:
                            # Selection crosses boundary - manually delete only editable part
                            base = self.text()[:self._base_end_pos]
                            # Ensure we don't delete the entire base
                            if base and self._base_end_pos > 0:
                                self.blockSignals(True)
                                self.setText(base)
                                self.setCursorPosition(self._base_end_pos)
                                self.blockSignals(False)
                                self._on_text_changed(base)
                            return True  # Block default deletion
                # Check if cursor is at or before the protected base
                elif self.cursorPosition() <= self._base_end_pos:
                    # Block deletion of protected text
                    return True
            elif key == Qt.Key_Delete:
                # Check if selection or cursor would delete protected text
                if self.hasSelectedText():
                    start = min(self.selectionStart(), self.selectionEnd())
                    end = max(self.selectionStart(), self.selectionEnd())
                    # If selection includes any protected text, adjust or block deletion
                    if start < self._base_end_pos:
                        # Selection starts in protected area
                        if end <= self._base_end_pos:
                            # Entire selection is in protected area, block deletion
                            return True
                        else:
                            # Selection crosses boundary - manually delete only editable part
                            base = self.text()[:self._base_end_pos]
                            # Ensure we don't delete the entire base
                            if base and self._base_end_pos > 0:
                                self.blockSignals(True)
                                self.setText(base)
                                self.setCursorPosition(self._base_end_pos)
                                self.blockSignals(False)
                                self._on_text_changed(base)
                            return True  # Block default deletion
                elif self.cursorPosition() < self._base_end_pos:
                    # Cursor is in protected area, block deletion
                    return True
            
            # Handle Left/Right arrow at boundary
            elif key == Qt.Key_Left:
                # If at start of editable area, prevent going into protected area
                if self.cursorPosition() == self._base_end_pos and not (mods & Qt.ShiftModifier):
                    return True
            elif key == Qt.Key_Right:
                # Allow movement, no protection needed
                pass
            
            # Handle paste - check if full URL is being pasted
            elif (mods & Qt.ControlModifier) and key == Qt.Key_V:
                clipboard = QApplication.clipboard()
                pasted_text = clipboard.text()
                
                # Check if pasted text looks like a full URL
                if self._is_full_url(pasted_text):
                    # User is pasting a full URL, so update the base
                    self.set_full(pasted_text, lock_to_origin=True)
                    return True  # Prevent default paste behavior
                # Otherwise, let QLineEdit handle normal paste
        
        return super().eventFilter(obj, ev)

    # ---- Internals ----------------------------------------------------------

    def _is_full_url(self, text: str) -> bool:
        """Check if text looks like a full URL (has scheme or contains host/path patterns)."""
        if not text or not text.strip():
            return False
            
        text = text.strip()
        
        # Check for explicit schemes
        if text.startswith(("http://", "https://", "file://", "ftp://", "about:", "chrome:")):
            return True
        
        # Check for hostname patterns (localhost, IP addresses, domains)
        # Look for patterns like "host" or "host:port" or "host/path"
        parts = text.split("/", 1)
        host_part = parts[0]
        
        # Check for localhost or IP-like patterns
        if host_part in ("localhost", "127.0.0.1", "::1") or self._looks_like_ip(host_part):
            return True
            
        # Check if it contains a dot and looks like a domain
        if "." in host_part and ":" in host_part:
            # Has both dot and colon (likely domain:port)
            return True
        elif "." in host_part and len(host_part.split(".")) >= 2:
            # Has dots and looks like a domain
            return True
            
        return False
    
    def _looks_like_ip(self, text: str) -> bool:
        """Check if text looks like an IP address."""
        # Check for IPv4 pattern
        parts = text.split(".")
        if len(parts) == 4:
            try:
                for part in parts:
                    num = int(part)
                    if not 0 <= num <= 255:
                        return False
                return True
            except ValueError:
                pass
        
        # Check for IPv6 pattern (simplified check)
        if ":" in text and (text.startswith("[") or not text.startswith("/")):
            # Look for patterns like [::1] or ::1 or IPv6 addresses
            # Remove brackets if present
            clean = text.strip("[]")
            if clean.count(":") >= 2:
                return True
                
        return False

    def _on_return(self):
        self.urlEntered.emit(self.full())

    def _on_text_changed(self, text):
        self.textChangedFull.emit(text)
    
    def _show_context_menu(self, pos: QPoint):
        """Show context menu with standard actions."""
        menu = QMenu(self)
        
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(self._copy_selected)
        
        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(self._handle_paste)
        
        cut_action = menu.addAction("Cut")
        cut_action.triggered.connect(self._cut_selected)
        
        select_all_action = menu.addAction("Select All")
        select_all_action.triggered.connect(self.selectAll)
        
        # Show menu at cursor position
        menu.exec(self.mapToGlobal(pos))
    
    def _copy_selected(self):
        """Copy selected text."""
        if self.hasSelectedText():
            clipboard = QApplication.clipboard()
            clipboard.setText(self.selectedText())
    
    def _cut_selected(self):
        """Cut selected text."""
        if self.hasSelectedText():
            start = min(self.selectionStart(), self.selectionEnd())
            end = max(self.selectionStart(), self.selectionEnd())
            # Only allow cutting if selection is not in protected area
            if start >= self._base_end_pos:
                clipboard = QApplication.clipboard()
                clipboard.setText(self.selectedText())
                self.del_()  # Delete selected text
            elif start < self._base_end_pos and end > self._base_end_pos:
                # Selection crosses boundary - only cut editable part
                editable_text = self.text()[self._base_end_pos:]
                clipboard = QApplication.clipboard()
                clipboard.setText(editable_text)
                base = self.text()[:self._base_end_pos]
                self.blockSignals(True)
                self.setText(base)
                self.setCursorPosition(self._base_end_pos)
                self.blockSignals(False)
                self._on_text_changed(base)
    
    def _handle_paste(self):
        """Handle paste from context menu (same as Ctrl+V handler)."""
        clipboard = QApplication.clipboard()
        pasted_text = clipboard.text()
        
        # Check if pasted text looks like a full URL
        if self._is_full_url(pasted_text):
            # User is pasting a full URL, so update the base
            self.set_full(pasted_text, lock_to_origin=True)
        else:
            # Normal paste
            self.paste()
