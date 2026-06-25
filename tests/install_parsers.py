from __future__ import annotations

import ast
import re
from pathlib import Path

FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS: frozenset[str] = frozenset(
    {
        "_LOW_LIGHT_HOLD_PEAK",
        "_HUE_STABLE_MIN_CHROMA",
        "apply_output_quantization_hold",
    }
)

REQUIRED_RUNTIME_VERIFIER_ASSETS: tuple[str, ...] = (
    "VERSION",
    "ui/style.qss",
    "assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg",
    "assets/udev/60-nanoleaf-kde-sync.rules",
    "capture/nanoleaf_drm_helper",
)


def repo_path(root: Path, relative: str) -> Path:
    return root / relative


def parse_pkgbuild(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")

    def _field(name: str) -> str:
        match = re.search(rf"^{name}=(.+)$", text, flags=re.MULTILINE)
        if match is None:
            raise ValueError(f"Missing PKGBUILD field: {name}")
        return match.group(1).strip().strip("'\"")

    sha_match = re.search(r"^sha256sums=\((.+)\)$", text, flags=re.MULTILINE)
    if sha_match is None:
        raise ValueError("Missing PKGBUILD sha256sums assignment")
    sha_values = tuple(
        value.strip().strip("'\"") for value in sha_match.group(1).split() if value.strip()
    )
    return {
        "pkgver": _field("pkgver"),
        "pkgrel": _field("pkgrel"),
        "sha256sums": sha_values,
    }


def parse_srcinfo(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        fields[key] = value
    return fields


def shell_non_comment_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def shell_contains_command(path: Path, command: str) -> bool:
    return any(command in line for line in shell_non_comment_lines(path))


def workflow_step_runs(path: Path) -> list[str]:
    runs: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s+run:\s*(.+)$", raw_line)
        if match is not None:
            runs.append(match.group(1).strip())
    return runs


def composite_action_run_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks: list[str] = []
    capture = False
    buffer: list[str] = []
    for raw_line in text.splitlines():
        if re.match(r"^\s+run:\s*\|\s*$", raw_line):
            capture = True
            buffer = []
            continue
        if capture:
            if raw_line and not raw_line.startswith((" ", "\t")):
                capture = False
                blocks.append("\n".join(buffer).strip())
                buffer = []
                continue
            buffer.append(raw_line.strip())
    if buffer:
        blocks.append("\n".join(buffer).strip())
    return blocks


def runtime_verifier_required_assets(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.ListComp):
                for generator in child.generators:
                    iterator = generator.iter
                    if isinstance(iterator, ast.Tuple):
                        values = [
                            element.value
                            for element in iterator.elts
                            if isinstance(element, ast.Constant) and isinstance(element.value, str)
                        ]
                        if values:
                            return tuple(values)
            if isinstance(child, ast.For):
                iterator = child.iter
                if isinstance(iterator, ast.Tuple):
                    values = [
                        element.value
                        for element in iterator.elts
                        if isinstance(element, ast.Constant) and isinstance(element.value, str)
                    ]
                    if values:
                        return tuple(values)
    raise ValueError("Could not find required asset tuple in verify_runtime_install.main()")


def runtime_verifier_references_forbidden_symbols(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for symbol in FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS:
                if symbol in node.value:
                    referenced.add(symbol)
    if any(symbol in text for symbol in FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS):
        referenced.update(symbol for symbol in FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS if symbol in text)
    return referenced & FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS


def runtime_verifier_checks_package_version(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            version_arg = node.args[1]
            if isinstance(version_arg, ast.Constant) and version_arg.value == "__version__":
                return True
    return False
