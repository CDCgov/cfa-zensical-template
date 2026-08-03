# Getting started

!!! warning

    CFA policy requires that publicly-available documentation should only by used for documentation of software, not scientific results or publications.

!!! tip

     If you're migrating from mkdocs, see [those instructions](#migrating-from-mkdocs).

## Enable zensical for your project

1. Ensure you have at least `docs/index.md`.
1. Copy `zensical.toml` to your repo. Update the block at the top and remove unneeded plugins.
1. Copy `.github/workflows/docs.yaml`. In your repo, set Settings | Pages | Source to GitHub Actions.
1. Add dependencies.
   - At a minimum, `zensical`.
   - We also recommend `mdx-truly-sane-lists`.
   - If you are building python API docs, also `mkdocstrings-python`.
   - You may want to add these to a separate group, for example using `uv add --group docs` or `uv add --dev`.
1. Ensure that `site/` is git-ignored but `docs/` is not.
1. Check that you can `zensical serve`.
1. See the [example static page](example.md) and zensical docs for more information about features like math rendering.
1. See the [example API docs](api.md), which document the toy code in `mkdtemp/`.

## Migrating from mkdocs

The workflow is somewhat different if you are migrating from [mkdocs](https://www.mkdocs.org/).

1. `uv remove mkdocs mkdocs-material`. You may need a `--group` argument.
1. `uv add zensical mdx-truly-sane-lists`. You might want a `--group` argument.
1. Remove `mkdocs.yaml`
1. Copy and update `zensical.toml`
1. Consider deleting `docs/javascript`
1. Update GitHub workflow
   - Change the filename
   - Change name of the workflow
   - Use zensical, not mkdocs
1. Update notes in the readme

## Interactive tool

This repo implements an experimental, interactive tool that automates new zensical setup and mkdocs migration. Run the tool using [uv](https://docs.astral.sh/uv/):

```
uvx --from git+https://github.com/CDCgov/cfa-zensical-template cfadoc
```

See the [API reference](api.md) for details about the `cfadoc` package.
