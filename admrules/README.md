# admrules

Administrative rules pipeline package for `target=admrul`.

Scope:

- `api_client.py`: `admrul` and `admrulOldAndNew` API wrappers.
- `cache.py`: raw history detail XML cache under `.cache/admrule/`.
- `checkpoint.py`: resumable page/detail checkpoint.
- `fetch_cache.py`: `history=True` / `nw=2` history list and detail cache fetch loop.
- `converter.py`: raw XML to Markdown/frontmatter.
- `render_spec.md`: path and frontmatter rendering contract mirrored by the Rust compiler.
- `byls_metadata.py`: attachment metadata helpers.
- `validate.py`: frontmatter and binary-free invariant checks.

Full unfiltered `fetch_cache.py` runs prune `.cache/admrule/*.xml` files that are
not present in the latest `history=True` / `nw=2` search result, so compiler
input stays reproducible from a fresh history cache.

`import_admrules.py` writes revisions in `발령일자`, `행정규칙일련번호`, path order.
The rule identity is `행정규칙ID`, falling back to `행정규칙일련번호` only when
the ID is missing. Revisions that contain `폐지` delete the latest file for that
identity from `HEAD`; earlier text remains available in Git history.
