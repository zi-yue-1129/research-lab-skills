"""Narrow anchored ordinary-file primitives for workflow transactions."""

from __future__ import annotations

import os
import stat

from presentation_no_follow import AnchoredPath


def remove_staged_siblings(anchored: AnchoredPath) -> None:
    """Remove regular transaction temporaries for one locked target.

    Args:
        anchored: Retained parent and target leaf identity.

    Raises:
        OSError: If a matching sibling is unsafe or cannot be removed.
    """
    prefix = f".{anchored.leaf_name}.transaction."
    for name in os.listdir(anchored.parent_fd):
        if not name.startswith(prefix) or not name.endswith(".tmp"):
            continue
        metadata = os.stat(name, dir_fd=anchored.parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"transaction temporary must be regular: {name}")
        os.unlink(name, dir_fd=anchored.parent_fd)
    anchored.fsync_parent()
