# Getting started

!!! tip

     If you're migrating from mkdocs, see [those instructions](migrating_from_mkdocs.md).

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
