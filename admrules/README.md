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
- `snapshot.py`: source-current selection and final tree reconciliation.
- `validate.py`: frontmatter, binary files, and current source coverage.

The default fetch omits `knd` and collects all rule types with `nw=2`.
An explicit `--knd` restricts a probe to the requested types.
The collector rejects incomplete pages, duplicate serials within a query, and changing totals.
A full successful fetch moves withdrawn XML into `admrule/retired/` after it saves the current selection.
Python and Rust retain this XML in publication history. Active XML takes precedence for duplicate serials.
The cache analyzer includes archived XML with the same precedence.
Failed or partial fetches do not archive XML.
Detail responses must contain the requested serial before they replace cached XML.

Verified upstream detail failures use serial-specific exceptions in `data/known_detail_failures.yaml`.
Each exception matches a recorded error and has an expiration date.
The collector counts these failures as `known_failures` and retries them on each fetch.
It does not cache no-result XML or mark the serial as processed.
Unknown serials, changed errors, and expired exceptions still stop a full fetch.
An exception cannot bypass the required detail for a listed current rule.

The exception for `2100000287624` expires on 2026-12-03.
Its evidence is in `tests/fixtures/admrule_no_result_2100000287624.json` at the repository root.
The no-result response does not establish legal repeal.

`import_admrules.py` writes revisions in `발령일자`, `행정규칙일련번호`, path order.
The rule identity is `행정규칙ID`, falling back to `행정규칙일련번호` only when
the ID is missing. Repeal codes `200404` and `200410` delete the latest file
for that identity. `200407` (`폐지제정`) writes a replacement body.
If the code is absent, the converter compares the exact names `폐지` and `타법폐지`.
Earlier text remains in Git history.

## Current selection

A full fetch also collects `nw=1` without a date or kind filter.
This response includes historical rows, so only rows marked `현행` select a current revision.
Explicit repeals are recorded as exclusions.
The pipeline saves `.cache/admrule/current_snapshot.json` after all selected details are available.
Its schema contains `schema_version: 1`, `observed_on` (KST date), `rules` (ID to serial), `excluded`, `supplemental`, and `conflicts`.
A missing search row does not prove repeal.
The pipeline rechecks absent candidates whose latest cached detail says `Y`.
It retains a candidate if the live detail still says `Y` and records this discrepancy in `supplemental`.
Daily updates recheck these retained rules even outside the publication window.
If the current list omits a rule, the pipeline probes its live detail.
An explicit no-result response adds `live_detail_no_result` to `excluded`.
It preserves cached XML and publication history and retries the excluded detail on later runs.
This exclusion does not establish legal repeal.
A no-result response for a listed current rule still stops the update.
API errors or unexpected response roots stop this recheck without replacing the selection.
`conflicts` records selected rows whose cached detail still says `N`. The selection preserves these rows instead of silently dropping them.
The selection follows the API classification. It does not infer legal validity from an effective date alone.
If the current list selects an older revision than the history list, previous snapshot, or published tree, the pipeline rechecks the competing details before saving a snapshot.
A unique live current revision can replace the listed revision once its effective date has arrived.
A newer revision that explicitly returns no result remains in cached history and is recorded in `excluded`.
If an omitted ID's serial is now assigned to a different ID, the selection records the reassignment only when the live status agrees with the selected revision for that new ID.
The older revision can stay current when the live details confirm that selection.
An ambiguous result stops the update before replacing the snapshot.
The pipeline records a corrected selection as `older_current_list_revision` in `conflicts`.

Full rebuilds preserve publication history, then materialize this selection.
If the final tree differs from the history tip, the rebuild records the complete adjustment in one commit dated on the observation day.
A full Python rebuild with `--commit` requires a fresh Git repository.
A repeal whose predecessor is absent still creates a publication commit, with no file changes.

The daily cache refresh reads the published branch history and requests missing XML for previously published serials absent from the list. Recovered XML moves to `retired/` during pruning. Keep the previous Git tip under an archive ref to preserve historical revisions whose detail endpoint returns no result.
A future revision remains in history while the selected earlier revision remains in `HEAD`.
A full Git rebuild requires the snapshot. When only rendering old XML or running a limited probe, the output shows publication history. A cached `현행여부=N` is an observation about the revision, not a dated repeal. Only explicit repeal revisions delete a document during replay. Pass `--published-repo` to the full cache fetch to compare the selection and body with the existing checkout.
Limited compiler probes do not apply the full snapshot.
Full Python imports validate the snapshot and its selected details before they write files.
Both implementations require a canonical `YYYY-MM-DD` observation date.
New snapshots include `required_body_ids`, the selected IDs whose text or original document attachments must remain available.
The pipeline retains this requirement while an ID remains selected.
Python import and Rust compilation stop before output if these IDs provide neither text nor original document attachments.
The publication validator also rejects `parsing-failed` for these IDs.
Old snapshots without this field remain readable. Regenerate them with the pipeline before recovery.
Rules without source text or original document attachments from the start can retain their existing notice.

Daily updates collect this selection beyond the 14-day publication window.
They refresh a selected cached detail if its `현행여부` remains `N`.
If a selected ID differs from its cached detail, the pipeline refreshes that detail.
If the refreshed ID still differs, the pipeline stops before it saves the selection.
Before publication, daily updates compare each selected cached document with the published document.
If the text differs or the document is missing, they fetch the selected detail again, including cached `Y` records.
A failed fetch or identity mismatch stops the update before publication.
A lost body stops the update if the published document previously contained text or original document attachments.
The update reports the additional published-body detail checks as `snapshot_refetched`.
The daily update tests new revisions in a detached worktree and fast-forwards only if the resulting files match the verified selection.
If a historical backfill, activation, withdrawal, or correction requires a different tree, the daily update reports `rebuild required`.
Validate and compare a fresh compiler output before replacing the published repository.
Partial workflow probes cannot push and do not apply the global selection.
Import deduplication reads the current branch history. An archive branch does not suppress a missing revision in `main`.

After a full import, make sure that the files match the selection:

```bash
python -m admrules.validate ../admrule-kr --snapshot ../.cache/admrule/current_snapshot.json
```

The validator reports missing IDs, extra IDs, duplicate IDs, and incorrect revision serials.
New source types remain in the fetch results and produce warnings.
Add a new legitimate type to `VALID_ADMRULE_TYPES` before it passes the file validator.

If inline text is absent, the converter preserves original `첨부파일명` and `첨부파일링크` pairs.
It records these files as `원문첨부` and uses `본문출처: attachment-only`.
The Markdown body links to these documents. A `별표` alone does not replace the original body.
Both implementations accept original document attachments for `required_body_ids`.
