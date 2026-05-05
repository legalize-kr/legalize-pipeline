# admrules

Administrative rules pipeline package for `target=admrul`.

Current scope is M1 read-side bootstrap:

- `api_client.py`: `admrul` and `admrulOldAndNew` API wrappers.
- `cache.py`: raw detail XML cache under `.cache/admrule/`.
- `checkpoint.py`: resumable page/detail checkpoint.
- `fetch_cache.py`: current-rule list and detail cache fetch loop.
- `converter.py`: raw XML to Markdown/frontmatter.
- `render_spec.md`: path and frontmatter rendering contract mirrored by the Rust compiler.
- `byls_metadata.py`: attachment metadata helpers.
- `validate.py`: frontmatter and binary-free invariant checks.

Write-side import/rebuild and Git commit history generation are intentionally
left for M2 after the shared core git engine contract is settled.
