from __future__ import annotations

from nanoleaf_sync.ui.qt_lazy import load_qt

_qt = load_qt()
QDialog = _qt["QDialog"]
QHBoxLayout = _qt["QHBoxLayout"]
QPlainTextEdit = _qt["QPlainTextEdit"]
QPushButton = _qt["QPushButton"]
QVBoxLayout = _qt["QVBoxLayout"]
QWidget = _qt["QWidget"]


class CommandResultsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        body: str,
        returncode: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        self.setMinimumSize(480, 280)

        root = QVBoxLayout(self)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        header = f"Exit code: {returncode}\n\n" if returncode is not None else ""
        editor.setPlainText(f"{header}{body}".strip())
        root.addWidget(editor)

        row = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        close_btn = QPushButton("Close")

        def _copy() -> None:
            app = _qt.get("QApplication")
            clipboard = app.clipboard() if app is not None else None
            if clipboard is not None:
                clipboard.setText(editor.toPlainText())

        copy_btn.clicked.connect(_copy)
        close_btn.clicked.connect(self.accept)
        row.addWidget(copy_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        root.addLayout(row)


def show_command_results(
    parent: QWidget | None,
    *,
    title: str,
    body: str,
    returncode: int | None = None,
) -> None:
    dialog = CommandResultsDialog(
        parent,
        title=title,
        body=body,
        returncode=returncode,
    )
    exec_fn = getattr(dialog, "exec", None)
    if callable(exec_fn):
        exec_fn()
