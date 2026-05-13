"""Pure-logic edits to a process-bigraph composite document.

Used by the Composite Explorer editor (live in-memory edits via the
dashboard) and by tests. No I/O — every function mutates the document in
place (or returns the mutated row list, for ``walk_process_configs``).
"""
from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# Process / config walking (Configure tab)
# ---------------------------------------------------------------------------

def walk_process_configs(doc: dict) -> list[dict]:
    """Return one row per process with its config keys + defaults + units.

    Row shape::

        {
            'name': '<process node name>',
            'address': '<local:ProcessClass>',
            'configs': [
                {'key': '<config key>', 'value': <current value>,
                 'default': <from parameters block, if any>,
                 'units': <from parameters block, if any>,
                 'description': <from parameters block, if any>},
                ...
            ],
        }
    """
    state = doc.get('state') or {}
    params = doc.get('parameters') or {}
    rows: list[dict] = []
    for name, node in state.items():
        if not isinstance(node, dict) or node.get('_type') != 'process':
            continue
        configs = []
        for key, val in (node.get('config') or {}).items():
            entry: dict = {'key': key, 'value': val}
            p = params.get(key)
            if isinstance(p, dict):
                if 'default' in p:
                    entry['default'] = p['default']
                if 'units' in p:
                    entry['units'] = p['units']
                if 'description' in p:
                    entry['description'] = p['description']
            else:
                # Fall back to the literal value as the "default"
                entry['default'] = val
                entry['units'] = None
            configs.append(entry)
        rows.append({
            'name': name,
            'address': node.get('address', ''),
            'configs': configs,
        })
    return rows


def apply_config_update(doc: dict, process_name: str, key: str, value: Any) -> None:
    """Mutate ``doc['state'][process_name]['config'][key] = value``.

    Raises ``KeyError`` if the process or key doesn't exist.
    """
    state = doc.get('state') or {}
    if process_name not in state:
        raise KeyError(f"unknown process {process_name!r}")
    node = state[process_name]
    if not isinstance(node, dict) or node.get('_type') != 'process':
        raise KeyError(f"{process_name!r} is not a process node")
    cfg = node.setdefault('config', {})
    if key not in cfg:
        raise KeyError(f"{process_name!r}.config has no key {key!r}")
    cfg[key] = value


# ---------------------------------------------------------------------------
# Emitter step (Observables tab)
# ---------------------------------------------------------------------------

def _resolve_leaf(state: dict, path: list) -> Any | None:
    """Walk ``state`` following ``path`` segments; return the leaf node or None."""
    node: Any = state
    for seg in path:
        if not isinstance(node, dict) or seg not in node:
            return None
        node = node[seg]
    return node


def inject_emitter(doc: dict, paths: list, address: str = 'local:SQLiteEmitter') -> None:
    """Rewrite ``doc['state']['emitter']`` so it records the given paths.

    Paths not present in the state are skipped silently.
    If ``paths`` is empty, ``emitter`` is removed from state entirely.
    """
    state = doc.setdefault('state', {})
    if not paths:
        state.pop('emitter', None)
        return

    inputs: dict = {}
    emit_schema: dict = {}
    for path in paths:
        leaf = _resolve_leaf(state, path)
        if leaf is None:
            continue
        port_name = path[-1] if path else 'state'
        inputs[port_name] = list(path)
        if isinstance(leaf, dict) and leaf.get('_type'):
            emit_schema[port_name] = leaf['_type']
        else:
            emit_schema[port_name] = 'any'

    if not inputs:
        # All paths missing → strip any prior emitter
        state.pop('emitter', None)
        return

    state['emitter'] = {
        '_type': 'step',
        'address': address,
        'config': {'emit': emit_schema},
        'inputs': inputs,
    }


def strip_emitter(doc: dict) -> None:
    """Remove the emitter step from ``doc['state']`` (idempotent)."""
    state = doc.get('state') or {}
    state.pop('emitter', None)


# ---------------------------------------------------------------------------
# Visualization step (Visualization tab)
# ---------------------------------------------------------------------------

def inject_viz_step(
    doc: dict,
    class_name: str,
    viz_inputs: dict,
    config: dict | None = None,
) -> None:
    """Rewrite ``doc['state']['viz']`` to call ``class_name`` with auto-wired inputs.

    Each viz input port is wired to ``['emitter', <port-name>]`` if the
    emitter step has a matching input port; otherwise omitted (indicating
    incomplete wiring to the user).
    """
    state = doc.setdefault('state', {})
    emitter = state.get('emitter') or {}
    emitter_ports: set = set((emitter.get('inputs') or {}).keys())

    wired: dict = {}
    for port_name in (viz_inputs or {}):
        if port_name in emitter_ports:
            wired[port_name] = ['emitter', port_name]

    entry: dict = {
        '_type': 'step',
        'address': f'local:{class_name}',
        'config': dict(config or {}),
    }
    if wired:
        entry['inputs'] = wired
    state['viz'] = entry


def strip_viz_step(doc: dict) -> None:
    """Remove the viz step from ``doc['state']`` (idempotent)."""
    state = doc.get('state') or {}
    state.pop('viz', None)
