# Copyright (C) 2023 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause
from __future__ import annotations

from functools import partial

from PySide6.QtWebEngineCore import (QWebEngineFileSystemAccessRequest,
                                     QWebEnginePage,
                                     QWebEngineWebAuthUxRequest,
                                     QWebEngineFullScreenRequest)
from PySide6.QtWebEngineWidgets import QWebEngineView

from PySide6.QtWidgets import QDialog, QMessageBox, QStyle, QMenu, QWidget, QVBoxLayout
from PySide6.QtGui import QIcon, QAction
from PySide6.QtNetwork import QAuthenticator
from PySide6.QtCore import QTimer, Signal, Slot, Qt

# Try to import spell checker - use pyspellchecker if available
try:
    from spellchecker import SpellChecker
    SPELL_CHECKER_AVAILABLE = True
except ImportError:
    SPELL_CHECKER_AVAILABLE = False
    SpellChecker = None

from webpage import WebPage
from webpopupwindow import WebPopupWindow
from ui_passworddialog import Ui_PasswordDialog
from ui_certificateerrordialog import Ui_CertificateErrorDialog
from webauthdialog import WebAuthDialog


def question_for_feature(feature):

    if feature == QWebEnginePage.Geolocation:
        return "Allow %1 to access your location information?"
    if feature == QWebEnginePage.MediaAudioCapture:
        return "Allow %1 to access your microphone?"
    if feature == QWebEnginePage.MediaVideoCapture:
        return "Allow %1 to access your webcam?"
    if feature == QWebEnginePage.MediaAudioVideoCapture:
        return "Allow %1 to access your microphone and webcam?"
    if feature == QWebEnginePage.MouseLock:
        return "Allow %1 to lock your mouse cursor?"
    if feature == QWebEnginePage.DesktopVideoCapture:
        return "Allow %1 to capture video of your desktop?"
    if feature == QWebEnginePage.DesktopAudioVideoCapture:
        return "Allow %1 to capture audio and video of your desktop?"
    if feature == QWebEnginePage.Notifications:
        return "Allow %1 to show notification on your desktop?"
    return ""


class WebView(QWebEngineView):

    web_action_enabled_changed = Signal(QWebEnginePage.WebAction, bool)
    fav_icon_changed = Signal(QIcon)
    dev_tools_requested = Signal(QWebEnginePage)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._load_progress = 100
        self.loadStarted.connect(self._load_started)
        self.loadProgress.connect(self._slot_load_progress)
        self.loadFinished.connect(self._load_finished)
        self.iconChanged.connect(self._emit_faviconchanged)
        self.renderProcessTerminated.connect(self._render_process_terminated)

        self._error_icon   = self.style().standardIcon(QStyle.SP_MessageBoxCritical)
        self._loading_icon = self.style().standardIcon(QStyle.SP_BrowserReload)
        self._default_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        self.auth_dialog = None
        self._fs_container = None
        
        # Initialize spell checker if available
        if SPELL_CHECKER_AVAILABLE:
            try:
                self._spell_checker = SpellChecker()
            except:
                self._spell_checker = None
        else:
            self._spell_checker = None

    @Slot()
    def _load_started(self):
        self._load_progress = 0
        self.fav_icon_changed.emit(self.fav_icon())

    @Slot(int)
    def _slot_load_progress(self, progress):
        self._load_progress = progress

    @Slot()
    def _emit_faviconchanged(self):
        self.fav_icon_changed.emit(self.fav_icon())

    @Slot(bool)
    def _load_finished(self, success):
        self._load_progress = 100 if success else -1
        self._emit_faviconchanged()

    @Slot(QWebEnginePage.RenderProcessTerminationStatus, int)
    def _render_process_terminated(self, termStatus, statusCode):
        status = ""
        if termStatus == QWebEnginePage.NormalTerminationStatus:
            status = "Render process normal exit"
        elif termStatus == QWebEnginePage.AbnormalTerminationStatus:
            status = "Render process abnormal exit"
        elif termStatus == QWebEnginePage.CrashedTerminationStatus:
            status = "Render process crashed"
        elif termStatus == QWebEnginePage.KilledTerminationStatus:
            status = "Render process killed"

        m = f"Render process exited with code: {statusCode:#x}\nDo you want to reload the page?"
        btn = QMessageBox.question(self.window(), status, m)
        if btn == QMessageBox.Yes:
            QTimer.singleShot(0, self.reload)

    def set_page(self, page):
        old_page = self.page()
        if old_page and isinstance(old_page, WebPage):
            old_page.createCertificateErrorDialog.disconnect(self.handle_certificate_error)
            old_page.authenticationRequired.disconnect(self.handle_authentication_required)
            old_page.featurePermissionRequested.disconnect(self.handle_feature_permission_requested)
            old_page.proxyAuthenticationRequired.disconnect(
                self.handle_proxy_authentication_required)
            old_page.registerProtocolHandlerRequested.disconnect(
                self.handle_register_protocol_handler_requested)
            old_page.webAuthUxRequested.disconnect(self.handle_web_auth_ux_requested)
            old_page.fileSystemAccessRequested.disconnect(self.handle_file_system_access_requested)
            old_page.fullScreenRequested.disconnect(self._on_fullscreen)

        self.create_web_action_trigger(page, QWebEnginePage.WebAction.Forward)
        self.create_web_action_trigger(page, QWebEnginePage.WebAction.Back)
        self.create_web_action_trigger(page, QWebEnginePage.WebAction.Reload)
        self.create_web_action_trigger(page, QWebEnginePage.WebAction.Stop)
        super().setPage(page)
        page.create_certificate_error_dialog.connect(self.handle_certificate_error)
        page.authenticationRequired.connect(self.handle_authentication_required)
        page.featurePermissionRequested.connect(self.handle_feature_permission_requested)
        page.proxyAuthenticationRequired.connect(self.handle_proxy_authentication_required)
        page.registerProtocolHandlerRequested.connect(
            self.handle_register_protocol_handler_requested)
        page.webAuthUxRequested.connect(self.handle_web_auth_ux_requested)
        page.fileSystemAccessRequested.connect(self.handle_file_system_access_requested)
        page.fullScreenRequested.connect(self._on_fullscreen)

    def load_progress(self):
        return self._load_progress

    def _emit_webactionenabledchanged(self, action, webAction):
        self.web_action_enabled_changed.emit(webAction, action.isEnabled())

    def create_web_action_trigger(self, page, webAction):
        action = page.action(webAction)
        action.changed.connect(partial(self._emit_webactionenabledchanged, action, webAction))

    def is_web_action_enabled(self, webAction):
        return self.page().action(webAction).isEnabled()

    def fav_icon(self):
        fav_icon = self.icon()
        if not fav_icon.isNull():
            return fav_icon
        if self._load_progress < 0:
            return self._error_icon
        if self._load_progress < 100:
            return self._loading_icon
        return self._default_icon

    def createWindow(self, type):
        main_window = self.window()
        if not main_window:
            return None

        if type == QWebEnginePage.WebBrowserTab:
            return main_window.tab_widget().create_tab()

        if type == QWebEnginePage.WebBrowserBackgroundTab:
            return main_window.tab_widget().create_background_tab()

        if type == QWebEnginePage.WebBrowserWindow:
            return main_window.browser().create_window().current_tab()

        if type == QWebEnginePage.WebDialog:
            view = WebView()
            WebPopupWindow(view, self.page().profile(), self.window())
            view.dev_tools_requested.connect(self.dev_tools_requested)
            return view

        return None

    @Slot()
    def _emit_devtools_requested(self):
        self.dev_tools_requested.emit(self.page())

    def handle_certificate_error(self, error):
        w = self.window()
        dialog = QDialog(w)
        dialog.setModal(True)

        certificate_dialog = Ui_CertificateErrorDialog()
        certificate_dialog.setupUi(dialog)
        certificate_dialog.m_iconLabel.setText("")
        icon = QIcon(w.style().standardIcon(QStyle.SP_MessageBoxWarning, None, w))
        certificate_dialog.m_iconLabel.setPixmap(icon.pixmap(32, 32))
        certificate_dialog.m_errorLabel.setText(error.description())
        dialog.setWindowTitle("Certificate Error")

        if dialog.exec() == QDialog.Accepted:
            error.acceptCertificate()
        else:
            error.rejectCertificate()

    def handle_authentication_required(self, requestUrl, auth):
        w = self.window()
        dialog = QDialog(w)
        dialog.setModal(True)

        password_dialog = Ui_PasswordDialog()
        password_dialog.setupUi(dialog)

        password_dialog.m_iconLabel.setText("")
        icon = QIcon(w.style().standardIcon(QStyle.SP_MessageBoxQuestion, None, w))
        password_dialog.m_iconLabel.setPixmap(icon.pixmap(32, 32))

        url_str = requestUrl.toString().toHtmlEscaped()
        realm = auth.realm()
        m = f'Enter username and password for "{realm}" at {url_str}'
        password_dialog.m_infoLabel.setText(m)
        password_dialog.m_infoLabel.setWordWrap(True)

        if dialog.exec() == QDialog.Accepted:
            auth.setUser(password_dialog.m_userNameLineEdit.text())
            auth.setPassword(password_dialog.m_passwordLineEdit.text())
        else:
            # Set authenticator null if dialog is cancelled
            auth = QAuthenticator()

    def handle_feature_permission_requested(self, securityOrigin, feature):
        title = "Permission Request"
        host = securityOrigin.host()
        question = question_for_feature(feature).replace("%1", host)
        w = self.window()
        page = self.page()
        if question and QMessageBox.question(w, title, question) == QMessageBox.Yes:
            page.setFeaturePermission(securityOrigin, feature,
                                      QWebEnginePage.PermissionGrantedByUser)
        else:
            page.setFeaturePermission(securityOrigin, feature,
                                      QWebEnginePage.PermissionDeniedByUser)

    def handle_proxy_authentication_required(self, url, auth, proxyHost):
        w = self.window()
        dialog = QDialog(w)
        dialog.setModal(True)

        password_dialog = Ui_PasswordDialog()
        password_dialog.setupUi(dialog)

        password_dialog.m_iconLabel.setText("")

        icon = QIcon(w.style().standardIcon(QStyle.SP_MessageBoxQuestion, None, w))
        password_dialog.m_iconLabel.setPixmap(icon.pixmap(32, 32))

        proxy = proxyHost.toHtmlEscaped()
        password_dialog.m_infoLabel.setText(f'Connect to proxy "{proxy}" using:')
        password_dialog.m_infoLabel.setWordWrap(True)

        if dialog.exec() == QDialog.Accepted:
            auth.setUser(password_dialog.m_userNameLineEdit.text())
            auth.setPassword(password_dialog.m_passwordLineEdit.text())
        else:
            # Set authenticator null if dialog is cancelled
            auth = QAuthenticator()

    def _on_fullscreen(self, req: QWebEngineFullScreenRequest):
        if req.toggleOn():
            # Use the BrowserWindow's fullscreen method if available
            browser_window = self.window()
            if browser_window and hasattr(browser_window, 'enter_fullscreen'):
                browser_window.enter_fullscreen()
                req.accept()
            else:
                # Fallback: create a borderless container and adopt this view
                if self._fs_container is None:
                    w = QWidget(self.window(), Qt.WindowType.Window)
                    w.setWindowFlags(w.windowFlags() | Qt.WindowType.FramelessWindowHint)
                    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                    layout = QVBoxLayout(w)
                    layout.setContentsMargins(0,0,0,0)
                    self.setParent(w)
                    layout.addWidget(self)
                    self._fs_container = w
                self._fs_container.showFullScreen()
                req.accept()
        else:
            # Exit fullscreen
            browser_window = self.window()
            if browser_window and hasattr(browser_window, 'exit_fullscreen'):
                browser_window.exit_fullscreen()
                req.accept()
            else:
                # Fallback: restore back into the tab widget
                if self._fs_container:
                    parent_tw = self.window().tab_widget()
                    self.setParent(parent_tw)
                    parent_tw.setCurrentWidget(self)
                    self._fs_container.close()
                    self._fs_container = None
                req.accept()

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        
        # Save the global position immediately (event will be deleted)
        self._context_menu_global_pos = event.globalPos()
        
        # JavaScript to get the word at cursor and check for spelling suggestions
        # We need to convert widget coordinates to page coordinates
        js_code = """
        (function() {
            var word = '';
            var isEditable = false;
            
            // Get selection first
            var selection = window.getSelection();
            var selectedText = selection.toString().trim();
            var range = null;
            
            if (selectedText && selection.rangeCount > 0) {
                // Use selected text
                range = selection.getRangeAt(0).cloneRange();
                word = selectedText.split(/\\s+/)[0]; // Get first word
                
                // Check if we're in an editable element
                var container = range.commonAncestorContainer;
                while (container && container.nodeType !== 1) {
                    container = container.parentElement;
                }
                if (container) {
                    isEditable = container.isContentEditable || 
                                 container.tagName === 'INPUT' || 
                                 container.tagName === 'TEXTAREA';
                }
            } else {
                // Try to get word at cursor position
                // Get the active element first
                var activeElement = document.activeElement;
                
                if (activeElement && (activeElement.isContentEditable || 
                                     activeElement.tagName === 'INPUT' || 
                                     activeElement.tagName === 'TEXTAREA')) {
                    isEditable = true;
                    
                    // For input/textarea, get word at cursor
                    if (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA') {
                        var start = activeElement.selectionStart;
                        var end = activeElement.selectionEnd;
                        
                        if (start === end && start !== null) {
                            // No selection, get word at cursor
                            var text = activeElement.value || activeElement.textContent || '';
                            var before = text.substring(0, start);
                            var after = text.substring(start);
                            
                            // Find word boundaries
                            var beforeMatch = before.match(/[\\w']+$/);
                            var afterMatch = after.match(/^[\\w']+/);
                            
                            if (beforeMatch || afterMatch) {
                                var wordStart = beforeMatch ? start - beforeMatch[0].length : start;
                                var wordEnd = afterMatch ? start + afterMatch[0].length : start;
                                word = text.substring(wordStart, wordEnd);
                            }
                        } else if (start !== end) {
                            // Selection exists
                            word = (activeElement.value || activeElement.textContent || '').substring(start, end).trim().split(/\\s+/)[0];
                        }
                    } else {
                        // ContentEditable element
                        if (selection.rangeCount > 0) {
                            range = selection.getRangeAt(0).cloneRange();
                            
                            // Expand to word
                            try {
                                range.expand('word');
                                word = range.toString().trim();
                            } catch (e) {
                                // Fallback: try to get word manually
                                var container = range.commonAncestorContainer;
                                if (container && container.nodeType === 3) { // Text node
                                    var text = container.textContent;
                                    var offset = range.startOffset;
                                    var before = text.substring(0, offset);
                                    var after = text.substring(offset);
                                    var beforeMatch = before.match(/[\\w']+$/);
                                    var afterMatch = after.match(/^[\\w']+/);
                                    if (beforeMatch || afterMatch) {
                                        word = (beforeMatch ? beforeMatch[0] : '') + (afterMatch ? afterMatch[0] : '');
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            // Clean word - remove extra whitespace and punctuation from edges
            if (word) {
                word = word.replace(/^[^\\w']+|[^\\w']+$/g, '');
            }
            
            // Return word info
            return JSON.stringify({
                word: word,
                isEditable: isEditable,
                hasSelection: selectedText.length > 0
            });
        })();
        """
        
        # Execute JavaScript and handle the result
        def handle_result(result):
            import json
            try:
                data = json.loads(result)
                word = data.get('word', '').strip()
                is_editable = data.get('isEditable', False)
                
                if word and is_editable and len(word) > 1:
                    # Word found in editable context - get suggestions via JavaScript
                    self._get_spell_suggestions(word, menu)
                else:
                    # No word found or not editable - show standard menu
                    self._finalize_context_menu(menu)
            except:
                # On error, just show standard menu
                self._finalize_context_menu(menu)
        
        # Use runJavaScript with callback
        self.page().runJavaScript(js_code, handle_result)
    
    def _get_spell_suggestions(self, word, menu):
        """Get spelling suggestions for a word using Python spell checker."""
        # Clean the word - remove punctuation
        import re
        clean_word = re.sub(r'[^\w]', '', word.lower())
        
        # Check if word is misspelled and get suggestions
        suggestions = []
        is_misspelled = False
        
        if self._spell_checker and clean_word and len(clean_word) > 1:
            try:
                # Check if the word is misspelled
                is_misspelled = clean_word in self._spell_checker.unknown([clean_word])
                if is_misspelled:
                    # Get suggestions
                    suggestions = self._spell_checker.candidates(clean_word)
                    # Limit to top 5 suggestions
                    suggestions = list(suggestions)[:5] if suggestions else []
            except:
                pass
        
        # Add suggestions to menu
        self._add_spell_suggestions_to_menu(menu, word, suggestions, is_misspelled)
        self._finalize_context_menu(menu)
    
    def _add_spell_suggestions_to_menu(self, menu, word, suggestions, is_misspelled):
        """Add spelling suggestions to the context menu."""
        if not suggestions and not is_misspelled:
            return
        
        # Insert spell suggestions after standard actions but before inspector
        actions = menu.actions()
        
        # Find where to insert (before inspect element or at the end)
        insert_pos = len(actions)
        for i, action in enumerate(actions):
            if action == self.page().action(QWebEnginePage.InspectElement):
                insert_pos = i
                break
        
        # Add separator before suggestions
        if insert_pos > 0:
            menu.insertSeparator(actions[insert_pos] if insert_pos < len(actions) else None)
        
        # Add suggestions
        if suggestions:
            for suggestion in suggestions:
                # Capitalize suggestion if original word was capitalized
                display_suggestion = suggestion
                if word and len(word) > 0 and word[0].isupper():
                    display_suggestion = suggestion.capitalize()
                
                # Create QAction first
                action = QAction(f"'{display_suggestion}'", menu)
                # Create a closure to capture the suggestion properly
                def make_replace_handler(orig_word, new_word):
                    return lambda: self._replace_misspelled_word(orig_word, new_word)
                action.triggered.connect(make_replace_handler(word, display_suggestion))
                
                # Insert the action
                before_action = actions[insert_pos] if insert_pos < len(actions) else None
                if before_action:
                    menu.insertAction(before_action, action)
                else:
                    menu.addAction(action)
        else:
            # Word is misspelled but no suggestions available
            no_suggestions_action = QAction(f"No suggestions for '{word}'", menu)
            no_suggestions_action.setEnabled(False)
            before_action = actions[insert_pos] if insert_pos < len(actions) else None
            if before_action:
                menu.insertAction(before_action, no_suggestions_action)
            else:
                menu.addAction(no_suggestions_action)
    
    def _finalize_context_menu(self, menu):
        """Finalize the context menu by adding standard actions and showing it."""
        actions = menu.actions()
        inspect_action = self.page().action(QWebEnginePage.InspectElement)
        if inspect_action in actions:
            inspect_action.setText("Inspect element")
        else:
            vs = self.page().action(QWebEnginePage.ViewSource)
            if vs not in actions:
                menu.addSeparator()

            action = menu.addAction("Open inspector in new window")
            action.triggered.connect(self._emit_devtools_requested)
        
        # Show the menu using the saved global position
        if hasattr(self, '_context_menu_global_pos'):
            menu.popup(self._context_menu_global_pos)
            delattr(self, '_context_menu_global_pos')
    
    def _replace_misspelled_word(self, old_word, new_word):
        """Replace a misspelled word with the selected suggestion."""
        # JavaScript to replace the word in the editable element
        js_code = """
        (function() {
            var oldWord = %s;
            var newWord = %s;
            
            var activeElement = document.activeElement;
            var replaced = false;
            
            // Handle input and textarea elements
            if (activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA')) {
                var start = activeElement.selectionStart;
                var end = activeElement.selectionEnd;
                var text = activeElement.value || '';
                
                if (start !== null && end !== null) {
                    if (start === end) {
                        // No selection - find word at cursor
                        var before = text.substring(0, start);
                        var after = text.substring(start);
                        var beforeMatch = before.match(/[\\w']+$/);
                        var afterMatch = after.match(/^[\\w']+/);
                        
                        if (beforeMatch || afterMatch) {
                            var wordStart = beforeMatch ? start - beforeMatch[0].length : start;
                            var wordEnd = afterMatch ? start + afterMatch[0].length : start;
                            var wordText = text.substring(wordStart, wordEnd);
                            
                            if (wordText.toLowerCase() === oldWord.toLowerCase()) {
                                var beforeText = text.substring(0, wordStart);
                                var afterText = text.substring(wordEnd);
                                activeElement.value = beforeText + newWord + afterText;
                                activeElement.selectionStart = activeElement.selectionEnd = wordStart + newWord.length;
                                replaced = true;
                            }
                        }
                    } else {
                        // Selection exists
                        var selectedText = text.substring(start, end).trim();
                        var firstWord = selectedText.split(/\\s+/)[0];
                        
                        if (firstWord.toLowerCase() === oldWord.toLowerCase()) {
                            var beforeText = text.substring(0, start);
                            var afterText = text.substring(end);
                            // Replace just the first word of selection
                            var restOfSelection = selectedText.substring(firstWord.length);
                            activeElement.value = beforeText + newWord + restOfSelection + afterText;
                            activeElement.selectionStart = start;
                            activeElement.selectionEnd = start + newWord.length + restOfSelection.length;
                            replaced = true;
                        }
                    }
                }
            } else {
                // Handle contentEditable elements
                var selection = window.getSelection();
                if (selection.rangeCount > 0) {
                    var range = selection.getRangeAt(0).cloneRange();
                    var text = range.toString().trim();
                    
                    if (text.toLowerCase() === oldWord.toLowerCase() || text.split(/\\s+/)[0].toLowerCase() === oldWord.toLowerCase()) {
                        // Replace the selection
                        range.deleteContents();
                        range.insertNode(document.createTextNode(newWord));
                        range.collapse(false);
                        selection.removeAllRanges();
                        selection.addRange(range);
                        replaced = true;
                    } else {
                        // Try to expand to word
                        try {
                            range.expand('word');
                            var wordText = range.toString().trim().replace(/^[^\\w']+|[^\\w']+$/g, '');
                            if (wordText.toLowerCase() === oldWord.toLowerCase()) {
                                range.deleteContents();
                                range.insertNode(document.createTextNode(newWord));
                                range.collapse(false);
                                selection.removeAllRanges();
                                selection.addRange(range);
                                replaced = true;
                            }
                        } catch (e) {
                            // Expansion failed, try manual approach
                            var container = range.commonAncestorContainer;
                            if (container && container.nodeType === 3) {
                                var nodeText = container.textContent;
                                var offset = range.startOffset;
                                var before = nodeText.substring(0, offset);
                                var after = nodeText.substring(offset);
                                var beforeMatch = before.match(/[\\w']+$/);
                                var afterMatch = after.match(/^[\\w']+/);
                                
                                if (beforeMatch || afterMatch) {
                                    var wordStart = beforeMatch ? offset - beforeMatch[0].length : offset;
                                    var wordEnd = afterMatch ? offset + afterMatch[0].length : offset;
                                    var wordText = nodeText.substring(wordStart, wordEnd);
                                    
                                    if (wordText.toLowerCase() === oldWord.toLowerCase()) {
                                        var newRange = document.createRange();
                                        newRange.setStart(container, wordStart);
                                        newRange.setEnd(container, wordEnd);
                                        newRange.deleteContents();
                                        newRange.insertNode(document.createTextNode(newWord));
                                        newRange.collapse(false);
                                        selection.removeAllRanges();
                                        selection.addRange(newRange);
                                        replaced = true;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            return replaced;
        })();
        """ % (
            repr(old_word),
            repr(new_word)
        )
        
        self.page().runJavaScript(js_code)


    def handle_web_auth_ux_requested(self, request):
        if self.auth_dialog:
            self.auth_dialog.deleteLater()

        self.auth_dialog = WebAuthDialog(request, self.window())
        self.auth_dialog.setModal(False)
        self.auth_dialog.setWindowFlags(self.auth_dialog.windowFlags()
                                        & ~Qt.WindowContextHelpButtonHint)

        request.stateChanged.connect(self.on_state_changed)
        self.auth_dialog.show()

    def on_state_changed(self, state):
        if state in (QWebEngineWebAuthUxRequest.WebAuthUxState.Completed,
                     QWebEngineWebAuthUxRequest.WebAuthUxState.Cancelled):
            if self.auth_dialog:
                self.auth_dialog.deleteLater()
                self.auth_dialog = None
        else:
            if self.auth_dialog:
                self.auth_dialog.update_display()

    def handle_register_protocol_handler_requested(self, request):
        host = request.origin().host()
        m = f"Allow {host} to open all {request.scheme()} links?"
        answer = QMessageBox.question(self.window(), "Permission Request", m)
        if answer == QMessageBox.Yes:
            request.accept()
        else:
            request.reject()

    def handle_file_system_access_requested(self, request):
        access_type = ""
        type = request.accessFlags()
        if type == QWebEngineFileSystemAccessRequest.Read:
            access_type = "read"
        elif type == QWebEngineFileSystemAccessRequest.Write:
            access_type = "write"
        elif type == (QWebEngineFileSystemAccessRequest.Read
                      | QWebEngineFileSystemAccessRequest.Write):
            access_type = "read and write"
        host = request.origin().host()
        path = request.filePath().toString()
        t = "File system access request"
        m = f"Give {host} {access_type} access to {path}?"
        answer = QMessageBox.question(self.window(), t, m)
        if answer == QMessageBox.Yes:
            request.accept()
        else:
            request.reject()
