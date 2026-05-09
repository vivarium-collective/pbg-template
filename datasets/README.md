# Datasets

Add datasets via `/pbg-data <model>`. Each dataset entry in `_index.yaml`
links to the model claims it serves.

Storage rules:
- Files <10MB are committed to git directly under a per-dataset subdir
- Larger files use `url:` + `sha256:` pointers; `lint-workspace.py` checks integrity
