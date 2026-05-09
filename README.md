# pbg-template

A standalone GitHub template for **process-bigraph research workspaces**.

## Two ways to use this

### Option A: GitHub "Use this template"
Click **Use this template** on github.com/eagmon/pbg-template, then in your new repo:

    bash template-init.sh

The script prompts for the workspace name and other parameters, then renders
the `.j2` files into their final form. No plugin required.

### Option B: via the `pbg-superpowers` plugin
If you have the `pbg-superpowers` Claude Code plugin installed:

    /pbg-workspace my-research-workspace

This clones this template, renders placeholders programmatically, initialises
git + venv, and walks the canonical workspace-bootstrap PR flow.

Either path produces the same workspace structure.
