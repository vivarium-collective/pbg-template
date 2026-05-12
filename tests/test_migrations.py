"""Tests for the workspace.yaml visualization migration classifier."""
from scripts._lib.migrations import classify_viz_entry


def test_classify_use_the_registered_class_pattern_with_match():
    entry = {
        'name': 'readdyplots',
        'description': 'Use the registered ReaDDyPlots class from the Registry. Run-time '
                       'instantiation of ReaDDyPlots against the gathered emitter results.',
    }
    classes = {'ReaDDyPlots', 'TimeSeriesPlot', 'Heatmap'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'auto-convert-to-class-backed'
    assert result['target_class'] == 'ReaDDyPlots'


def test_classify_use_the_registered_class_pattern_no_match():
    entry = {
        'name': 'unknown-class-ref',
        'description': 'Use the registered MissingThing class from the Registry.',
    }
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'defer'
    assert 'MissingThing' in result['reason']


def test_classify_wrapper_response_file_exists(tmp_path):
    entry = {'name': 'smoke-trajectory', 'description': 'Custom timeseries plot.'}
    responses_dir = tmp_path / '.pbg' / 'viz-responses'
    responses_dir.mkdir(parents=True)
    (responses_dir / 'smoke-trajectory.py').write_text('def visualize(results): return ""')
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes, workspace_root=tmp_path)
    assert result['action'] == 'regenerate-as-class'
    assert 'smoke-trajectory.py' in result['legacy_path']


def test_classify_description_only_no_response(tmp_path):
    entry = {'name': 'video-of-chromosome', 'description': 'a gif of the chromosome.'}
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes, workspace_root=tmp_path)
    assert result['action'] == 'regenerate-as-class'
    assert result.get('legacy_path') is None


def test_classify_already_class_backed_is_no_op():
    entry = {'name': 'free-DnaA', 'class': 'TimeSeriesPlot', 'config': {'observable': 'free_DnaA'}}
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'no-op'


def test_classify_legacy_structured_entry_no_class_no_description():
    entry = {'name': 'dnaA-trajectory', 'type': 'time-series', 'observables': ['DnaA']}
    classes = {'TimeSeriesPlot'}
    result = classify_viz_entry(entry, classes)
    assert result['action'] == 'defer'
    assert 'manual' in result['reason'].lower() or 'legacy structured' in result['reason'].lower()
