# Migrating from mkdocs

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
