"""Find the workspace root by walking up from __file__."""
from __future__ import annotations
from pathlib import Path


def workspace_root() -> Path:
    """Return the workspace root: the nearest ancestor containing workspace.yaml.

    Used by vendored helpers to locate `.pbg/schemas/`. Raises if no workspace
    root is found (e.g., the helpers were imported from outside a workspace).
    """
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / "workspace.yaml").exists():
            return candidate
    raise RuntimeError(
        f"workspace.yaml not found in any ancestor of {here}; "
        "scripts/_lib/* must run from inside a scaffolded workspace"
    )
