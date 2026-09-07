"""Windows font-registry backend for `fonts`.

`fonts` resolves families and locates font files through `fontconfig`, which
Windows does not ship. That made font resolution raise on Windows, and because
`resolve_font_stack` is reached by any slide declaring a `font-family`, it was
not a test-suite inconvenience -- it stopped a real deck from exporting at all.

Windows keeps the same information in its font registry: one value per installed
face, named for the face and pointing at its file. `Georgia Bold (TrueType)`
maps to `georgiab.ttf`. Reading it gives both answers `fonts` needs -- whether a
family is installed, and which file backs it at a given weight -- without
requiring the user to install fontconfig.

The parsing is the fiddly part. A value name is `<family> [style words] (<type>)`
and there is no separator between family and style, so `Arial Black` must not be
mistaken for the `Black` style of `Arial`. Style words are therefore stripped
only from the end, and only while what remains is non-empty, which keeps
`Arial Black`, `Segoe UI Black` and `Arial` distinct.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Registry locations holding installed faces: machine-wide, then per-user.
_FONT_KEYS = (
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
)

#: Style words that may trail a family name in a registry value.
_STYLE_WORDS = frozenset({
    "thin", "extralight", "ultralight", "light", "regular", "normal", "book",
    "medium", "demibold", "semibold", "bold", "extrabold", "ultrabold",
    "heavy", "italic", "oblique", "condensed", "narrow", "expanded",
})

#: Weight at or above which a bold face is preferred, matching CSS.
_BOLD_THRESHOLD = 600


def available() -> bool:
    """Report whether this platform exposes the Windows font registry.

    Returns:
        True on Windows with a readable registry.
    """
    try:
        import winreg  # noqa: F401
    except ImportError:
        return False
    return True


def _split_face(value_name: str) -> Tuple[str, List[str]]:
    """Split a registry value name into its family and style words.

    Args:
        value_name: A name such as `Georgia Bold Italic (TrueType)`.

    Returns:
        The family and its lower-cased style words. Style words are removed
        only from the end and never all of them, so `Arial Black` keeps its
        name rather than collapsing to `Arial`.
    """
    name = value_name.split("(")[0].strip()
    words = name.split()
    styles: List[str] = []
    while len(words) > 1 and words[-1].lower() in _STYLE_WORDS:
        styles.insert(0, words.pop().lower())
    return " ".join(words), styles


@functools.lru_cache(maxsize=1)
def _faces() -> Dict[str, List[Tuple[List[str], str]]]:
    """Read every installed face, keyed by lower-cased family.

    Cached because the registry is read once per process and enumerating it is
    the expensive part of every measurement.

    Returns:
        Family -> list of `(style words, file reference)`.
    """
    import winreg

    faces: Dict[str, List[Tuple[List[str], str]]] = {}
    for hive_name, sub_key in _FONT_KEYS:
        hive = getattr(winreg, hive_name)
        try:
            key = winreg.OpenKey(hive, sub_key)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    value_name, file_ref, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if not isinstance(file_ref, str) or not file_ref:
                    continue
                family, styles = _split_face(value_name)
                if family:
                    faces.setdefault(family.lower(), []).append((styles, file_ref))
    return faces


def is_family_available(family: str) -> bool:
    """Report whether a family is installed on this machine.

    Args:
        family: A concrete family name.

    Returns:
        True when at least one face of that family is registered.
    """
    return bool(_faces().get(family.strip().lower()))


def font_file_for(family: str, weight: int = 400) -> Optional[Path]:
    """Locate the file backing a family at a weight.

    Args:
        family: A concrete, installed family name.
        weight: CSS numeric weight; 600 and above prefers a bold face.

    Returns:
        The font file, or None when the family is not installed or its
        registered file cannot be found on disk.
    """
    candidates = _faces().get(family.strip().lower())
    if not candidates:
        return None

    want_bold = weight >= _BOLD_THRESHOLD
    # Upright faces first: an italic file would change every advance width, and
    # the caller asked only for a weight.
    ranked = sorted(
        candidates,
        key=lambda entry: (
            "italic" in entry[0] or "oblique" in entry[0],
            ("bold" in entry[0]) != want_bold,
            len(entry[0]),
        ),
    )
    for _styles, file_ref in ranked:
        path = _resolve_file(file_ref)
        if path is not None:
            return path
    return None


def _resolve_file(file_ref: str) -> Optional[Path]:
    """Turn a registry file reference into an existing path.

    A machine-wide face is registered by bare filename and lives in the Windows
    font directory; a user-installed face is registered by full path.

    Args:
        file_ref: The registry value's data.

    Returns:
        The existing path, or None.
    """
    candidate = Path(file_ref)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    for directory in _font_directories():
        path = directory / file_ref
        if path.is_file():
            return path
    return None


def _font_directories() -> Tuple[Path, ...]:
    """Return the directories a bare font filename may live in.

    Returns:
        The machine-wide font directory followed by the per-user one.
    """
    directories = []
    windir = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if windir:
        directories.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        directories.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    return tuple(directories)
