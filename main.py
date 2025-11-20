import sys
import os
import json
from argparse import ArgumentParser, RawTextHelpFormatter

from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PySide6.QtWidgets import QApplication, QStyle
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtCore import QCoreApplication, QLoggingCategory, QUrl, Qt

from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

from browser import Browser
from resources import resources_rc  # registers :/ resources

def load_config(path="config.json"):
    """Load configuration from a JSON file."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Config file not found at {path}. Using defaults.")
        return {}
    except json.JSONDecodeError as e:
        print(f"⚠️ Failed to parse config file: {e}")
        return {}


def slugify(name: str) -> str:
    import re
    s = re.sub(r"[\W_]+", "-", name.lower()).strip("-")
    return re.sub(r"-+", "-", s)

def apply_dark_palette(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()

    # Base tones
    p.setColor(QPalette.Window, QColor(37, 37, 38))
    p.setColor(QPalette.WindowText, Qt.white)
    p.setColor(QPalette.Base, QColor(30, 30, 30))
    p.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
    p.setColor(QPalette.ToolTipBase, Qt.white)
    p.setColor(QPalette.ToolTipText, Qt.white)
    p.setColor(QPalette.Text, Qt.white)
    p.setColor(QPalette.Button, QColor(45, 45, 48))
    p.setColor(QPalette.ButtonText, Qt.white)
    p.setColor(QPalette.BrightText, QColor(255, 85, 85))

    # Highlights / links
    p.setColor(QPalette.Highlight, QColor(10, 132, 255))
    p.setColor(QPalette.HighlightedText, Qt.white)
    p.setColor(QPalette.Link, QColor(125, 175, 255))

    # Disabled
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(160, 160, 160))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(160, 160, 160))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(160, 160, 160))

    app.setPalette(p)

    # A little extra polish via QSS
    app.setStyleSheet("""
        /* Toolbar */
        QToolBar { background: #2a2a2b; border: none; }

        /* Tabs */
        QTabBar::tab {
            background: #3a3a3c;
            color: white;
            padding: 6px 12px;
            padding-right: 24px; /* space for close button */
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #3f3f41;
            margin: 0 2px;
        }
        QTabBar::tab:selected {
            background: #4a4a4d;
            border: 1px solid #5a5a5f;
            color: white;
        }
        QTabBar::tab:hover {
            background: #454549;
        }

        /* Close button inside tabs */
        QTabBar::close-button {
            subcontrol-position: right;
            subcontrol-origin: padding;
            width: 16px; height: 16px;
            right: 6px; top: 6px;
            border-radius: 8px;
            image: url(:/close-x.svg);
        }
        QTabBar::close-button:hover {
            background: rgba(167, 167, 167, 0.18);
            image: url(:/close-x.svg);
        }
        QTabBar::close-button:pressed {
            background: rgba(167, 167, 167, 0.28);
            image: url(:/close-x.svg);
        }

        /* TabBar navigation/add buttons (modern rounded buttons) */
        QTabBar QToolButton {
            color: white;
            background: #3a3a3c;
            border: 1px solid #3f3f41;
            border-radius: 4px;
            padding: 1px 2px;
            margin: 2px;
            min-width: 20px; min-height: 20px;
        }
        QTabBar QToolButton:hover {
            background: #505053;
            border: 1px solid #5a5a5f;
        }
        QTabBar QToolButton:pressed {
            background: #2d2d2f;
            border: 1px solid #5a5a5f;
        }
        QTabBar QToolButton:focus {
            border: 1px solid #0a84ff;
        }
        QTabBar::left-button, QTabBar::right-button {
            width: 20px; height: 20px;
        }

        /* Progress */
        QProgressBar { background: transparent; border: 0; }
        QProgressBar::chunk { background: #0a84ff; }

        /* Generic tool buttons elsewhere */
        QToolButton { color: white; }
        QToolButton:hover { background: rgba(255,255,255,0.07); border-radius: 6px; }

        /* Inputs */
        QLineEdit {
            background: #2f2f31;
            border: 1px solid #3f3f41;
            color: white;
            padding: 4px 6px;
            border-radius: 6px;
        }
    """)

if __name__ == "__main__":
    parser = ArgumentParser(description="Browserless WADspaces",
                            formatter_class=RawTextHelpFormatter)
    parser.add_argument("--single-process", "-s", action="store_true",
                        help="Run in single process mode (trouble shooting)")
    parser.add_argument("--config", "-c", type=str, default="config.json",
                        help="Path to configuration file")
    parser.add_argument("url", type=str, nargs="?", help="URL")
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    app_name = config.get("app_name", "URL Redirect")
    app_url = config.get("app_url", "chrome://qt")
    icon_path = config.get("icon_path", "")

    os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "xcb"))
    os.environ["QTWEBENGINE_DICTIONARIES_PATH"] = "/usr/share/qt6/qtwebengine_dictionaries"
    # WebEngine flags: keep existing, add useful features
    # Conservative, Qt-friendly GPU flags (avoid unsupported GL switches and Vulkan)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join([
        "--enable-gpu",
        "--disable-zero-copy",
        "--disable-gpu-rasterization",
        "--ignore-gpu-blocklist",
        "--disable-features=UseSkiaRenderer,AcceleratedVideoDecode",
        "--disable-gpu-vsync",
        "--no-sandbox",  # safer for some environments than setuid sandbox
    ])

    slug = slugify(app_name)
    # Crucial: make task manager associate this process with the unique desktop file
    QGuiApplication.setDesktopFileName(slug)

    QCoreApplication.setOrganizationName("WAD")
    QCoreApplication.setApplicationName(app_name)

    app_args = sys.argv
    if args.single_process:
        app_args.extend(["--webEngineArgs", "--single-process"])

    app = QApplication(app_args)
    apply_dark_palette(app)
    app_icon = QIcon(icon_path)
    if app_icon.isNull():
        app_icon = QApplication.style().standardIcon(QStyle.SP_DesktopIcon)
    app.setWindowIcon(app_icon)
    QLoggingCategory.setFilterRules("qt.webenginecontext.debug=true")

    # Configure web engine
    s = QWebEngineProfile.defaultProfile().settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)

    url = args.url or app_url
    browser = Browser(url, app_name, app_icon)
    window = browser.create_window()

    sys.exit(app.exec())