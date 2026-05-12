"""Classify a workspace.yaml visualization entry into a migration action.

Used by both the dashboard's migration plan endpoint and the scripts/migrate-
visualizations.py CLI. Pure logic — pass in the entry + the set of currently
registered class names; get back a dict describing what to do.
"""
from __future__ import annotations
import re
from pathlib import Path


_USE_REGISTERED_CLASS_RE = re.compile(
    r'use the registered (\w+) class', re.IGNORECASE,
)


def classify_viz_entry(
    entry: dict,
    registered_classes: set,
    workspace_root: Path | None = None,
) -> dict:
    """Return a dict describing what to do with ``entry``.

    Returns:
        action: 'no-op' | 'auto-convert-to-class-backed' | 'regenerate-as-class' | 'defer'
        target_class: (when auto-convert) the class name to bind
        legacy_path: (when regenerate) path to the existing wrapper response file, if any
        reason: (when defer) human-readable explanation
    """
    # Already class-backed: nothing to do.
    if entry.get('class'):
        return {'action': 'no-op'}

    name = entry.get('name', '')
    description = entry.get('description') or ''

    # Pattern 1: "use the registered X class"
    match = _USE_REGISTERED_CLASS_RE.search(description)
    if match:
        target = match.group(1)
        if target in registered_classes:
            return {'action': 'auto-convert-to-class-backed', 'target_class': target}
        return {
            'action': 'defer',
            'reason': f'description refers to class {target!r} which is not currently registered',
        }

    # Pattern 2: legacy structured entry (type/observables, no description) —
    # not a /pbg-viz-style entry, can't be auto-classified.
    if entry.get('type') or entry.get('observables'):
        if not description:
            return {
                'action': 'defer',
                'reason': 'legacy structured entry (no description); manual migration recommended',
            }

    # Pattern 3: has description; check for existing wrapper response file.
    legacy_path = None
    if workspace_root and name:
        candidate = Path(workspace_root) / '.pbg' / 'viz-responses' / f'{name}.py'
        if candidate.is_file():
            legacy_path = str(candidate)

    return {
        'action': 'regenerate-as-class',
        'legacy_path': legacy_path,
    }
