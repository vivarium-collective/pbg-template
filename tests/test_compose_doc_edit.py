"""Tests for compose_doc_edit helpers — pure logic on composite documents."""
import copy

import pytest

from scripts._lib.compose_doc_edit import (
    walk_process_configs,
    apply_config_update,
    inject_emitter,
    strip_emitter,
    inject_viz_step,
    strip_viz_step,
)


def _doc():
    return {
        'name': 'demo',
        'parameters': {
            'partition_method': {'type': 'string', 'default': 'mukBEF-anchored',
                                  'description': 'partition algorithm'},
            'rate': {'type': 'float', 'default': 1.0, 'units': '1/s'},
        },
        'state': {
            'partitioner': {
                '_type': 'process',
                'address': 'local:ChromosomePartition',
                'config': {'partition_method': 'mukBEF-anchored', 'rate': 1.0},
                'inputs': {'chromosome': ['stores', 'chromosome']},
                'outputs': {'chromosome': ['stores', 'chromosome']},
            },
            'stores': {
                'chromosome': {
                    '_type': 'integer',
                    '_default': 1,
                },
            },
        },
    }


# walk_process_configs --------------------------------------------------

def test_walk_process_configs_yields_one_row_per_process():
    rows = walk_process_configs(_doc())
    assert len(rows) == 1
    row = rows[0]
    assert row['name'] == 'partitioner'
    assert row['address'] == 'local:ChromosomePartition'
    assert {c['key'] for c in row['configs']} == {'partition_method', 'rate'}


def test_walk_process_configs_includes_defaults_and_units_from_parameters_block():
    rows = walk_process_configs(_doc())
    cfg_by_key = {c['key']: c for c in rows[0]['configs']}
    # rate has units defined in the parameters block
    assert cfg_by_key['rate']['units'] == '1/s'
    assert cfg_by_key['rate']['default'] == 1.0
    # partition_method has a default but no units
    assert cfg_by_key['partition_method']['default'] == 'mukBEF-anchored'
    assert cfg_by_key['partition_method'].get('units') is None


def test_walk_process_configs_handles_doc_with_no_processes():
    doc = {'state': {'just_a_store': {'_type': 'integer', '_default': 5}}}
    assert walk_process_configs(doc) == []


# apply_config_update --------------------------------------------------

def test_apply_config_update_mutates_target_config_key():
    doc = _doc()
    apply_config_update(doc, 'partitioner', 'rate', 2.5)
    assert doc['state']['partitioner']['config']['rate'] == 2.5


def test_apply_config_update_unknown_process_raises():
    doc = _doc()
    with pytest.raises(KeyError, match='unknown'):
        apply_config_update(doc, 'unknown_process', 'rate', 2.5)


def test_apply_config_update_unknown_key_raises():
    doc = _doc()
    with pytest.raises(KeyError, match='unknown_key'):
        apply_config_update(doc, 'partitioner', 'unknown_key', 1.0)


# inject_emitter / strip_emitter ---------------------------------------

def test_inject_emitter_adds_step_wired_to_paths():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    em = doc['state']['emitter']
    assert em['_type'] == 'step'
    assert em['address'] == 'local:SQLiteEmitter'
    assert em['inputs']['chromosome'] == ['stores', 'chromosome']
    # type schema captures the leaf's _type when available
    assert em['config']['emit']['chromosome'] == 'integer'


def test_inject_emitter_ram_address():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']], address='local:RAMEmitter')
    assert doc['state']['emitter']['address'] == 'local:RAMEmitter'


def test_inject_emitter_skips_missing_paths():
    doc = _doc()
    inject_emitter(doc, paths=[
        ['stores', 'chromosome'],
        ['stores', 'nonexistent'],
    ])
    em = doc['state']['emitter']
    assert 'chromosome' in em['inputs']
    assert 'nonexistent' not in em['inputs']


def test_inject_emitter_with_no_paths_strips_emitter():
    doc = _doc()
    # First add then re-call with empty
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    assert 'emitter' in doc['state']
    inject_emitter(doc, paths=[])
    assert 'emitter' not in doc['state']


def test_strip_emitter_removes_step():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    strip_emitter(doc)
    assert 'emitter' not in doc['state']


def test_strip_emitter_idempotent():
    doc = _doc()
    assert 'emitter' not in doc['state']
    strip_emitter(doc)  # no-op
    assert 'emitter' not in doc['state']


# inject_viz_step / strip_viz_step -------------------------------------

def test_inject_viz_step_auto_wires_inputs_by_name():
    doc = _doc()
    inject_emitter(doc, paths=[['stores', 'chromosome']])
    # Emitter has port 'chromosome'; viz expects input 'chromosome' + 'time'
    inject_viz_step(
        doc,
        class_name='TimeSeriesPlot',
        viz_inputs={'chromosome': 'list[float]', 'time': 'list[float]'},
        config={'title': 'demo'},
    )
    viz = doc['state']['viz']
    assert viz['_type'] == 'step'
    assert viz['address'] == 'local:TimeSeriesPlot'
    assert viz['config'] == {'title': 'demo'}
    # 'chromosome' matches an emitter port → wired
    assert viz['inputs']['chromosome'] == ['emitter', 'chromosome']
    # 'time' has no matching emitter port → omitted from inputs
    assert 'time' not in viz['inputs']


def test_inject_viz_step_without_emitter_inputs_empty():
    doc = _doc()
    # No emitter present at all
    inject_viz_step(
        doc,
        class_name='TimeSeriesPlot',
        viz_inputs={'chromosome': 'list[float]'},
        config={},
    )
    viz = doc['state']['viz']
    assert viz['_type'] == 'step'
    # No emitter to wire to; inputs map empty
    assert viz.get('inputs', {}) == {}


def test_strip_viz_step_removes_step():
    doc = _doc()
    inject_viz_step(doc, 'TimeSeriesPlot', {'x': 'list[float]'}, {})
    strip_viz_step(doc)
    assert 'viz' not in doc['state']


def test_strip_viz_step_idempotent():
    doc = _doc()
    strip_viz_step(doc)  # no-op
    assert 'viz' not in doc['state']
