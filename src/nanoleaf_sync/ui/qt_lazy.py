from __future__ import annotations


def load_qt():
    """
    Import Qt modules lazily so non-UI usage doesn't fail if PyQt isn't installed.
    """

    try:
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtGui import QAction, QIcon, QPainter, QPixmap
        from PyQt6.QtWidgets import (
            QApplication,
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QGridLayout,
            QLabel,
            QMenu,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
            QSlider,
            QSystemTrayIcon,
        )
    except Exception as e:  # pragma: no cover
        raise RuntimeError("PyQt6 is required for the tray UI. Install `PyQt6`.") from e

    return {
        "QTimer": QTimer,
        "Qt": Qt,
        "QAction": QAction,
        "QIcon": QIcon,
        "QPainter": QPainter,
        "QPixmap": QPixmap,
        "QApplication": QApplication,
        "QDialog": QDialog,
        "QDialogButtonBox": QDialogButtonBox,
        "QGridLayout": QGridLayout,
        "QCheckBox": QCheckBox,
        "QLabel": QLabel,
        "QMenu": QMenu,
        "QMessageBox": QMessageBox,
        "QPushButton": QPushButton,
        "QVBoxLayout": QVBoxLayout,
        "QSlider": QSlider,
        "QSystemTrayIcon": QSystemTrayIcon,
    }
