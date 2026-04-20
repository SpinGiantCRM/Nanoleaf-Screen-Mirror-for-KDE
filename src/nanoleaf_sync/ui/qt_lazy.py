from __future__ import annotations


def load_qt():
    """
    Import Qt modules lazily so non-UI usage doesn't fail if PyQt isn't installed.
    """

    try:
        from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
        from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
        from PyQt6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QMenu,
            QMessageBox,
            QPushButton,
            QScrollArea,
            QSlider,
            QStackedWidget,
            QSystemTrayIcon,
            QVBoxLayout,
            QWidget,
        )
    except Exception as e:  # pragma: no cover
        raise RuntimeError("PyQt6 is required for the tray UI. Install `PyQt6`.") from e

    return {
        "QTimer": QTimer,
        "Qt": Qt,
        "QObject": QObject,
        "pyqtSignal": pyqtSignal,
        "QAction": QAction,
        "QColor": QColor,
        "QIcon": QIcon,
        "QPainter": QPainter,
        "QPixmap": QPixmap,
        "QApplication": QApplication,
        "QDialog": QDialog,
        "QDialogButtonBox": QDialogButtonBox,
        "QGridLayout": QGridLayout,
        "QCheckBox": QCheckBox,
        "QComboBox": QComboBox,
        "QGroupBox": QGroupBox,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QMenu": QMenu,
        "QMessageBox": QMessageBox,
        "QPushButton": QPushButton,
        "QScrollArea": QScrollArea,
        "QSlider": QSlider,
        "QStackedWidget": QStackedWidget,
        "QSystemTrayIcon": QSystemTrayIcon,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }
