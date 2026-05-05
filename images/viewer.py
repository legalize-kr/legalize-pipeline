"""Local image review viewer — a lightweight HTTP server for reviewing images.

Serves a single-page app that displays downloaded images alongside their
manifest metadata and surrounding document context, enabling manual review
and text entry for conversion.

Usage:
    python -m images viewer              # http://localhost:8765
    python -m images viewer --port 9000  # http://localhost:9000
"""

import json
import logging
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config
from .manifest import load_manifest

logger = logging.getLogger(__name__)


def _get_context(doc_path: str, line_number: int, lines: int = 3) -> str:
    """Read lines around the img tag in the source document."""
    full_path = config.KR_DIR.parent / doc_path
    if not full_path.exists():
        return ""
    try:
        all_lines = full_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    n = line_number - 1
    if n < 0 or n >= len(all_lines):
        return ""
    start = max(0, n - lines)
    end = min(len(all_lines), n + lines + 1)
    return "\n".join(all_lines[start:end])


def _find_image_file(image_id: str) -> Path | None:
    """Find cached image file for a given image_id."""
    for candidate in config.IMAGE_CACHE_DIR.glob(f"{image_id}.*"):
        if candidate.is_file():
            return candidate
    return None


class ViewerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the image review viewer."""

    def log_message(self, format, *args):
        logger.debug(format, *args)

    def _send_json(self, data: dict | list, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/":
            self._send_html(_INDEX_HTML)

        elif path == "/api/manifest":
            manifest = load_manifest()
            status_filter = params.get("status", [None])[0]
            tag_filter = params.get("tag_format", [None])[0]
            page = int(params.get("page", ["1"])[0])
            per_page = int(params.get("per_page", ["50"])[0])

            entries = manifest.entries
            if status_filter:
                entries = [e for e in entries if e.status == status_filter]
            if tag_filter:
                entries = [e for e in entries if e.tag_format == tag_filter]

            total = len(entries)
            entries = sorted(entries, key=lambda e: e.priority)
            start = (page - 1) * per_page
            page_entries = entries[start:start + per_page]

            self._send_json({
                "total": total,
                "page": page,
                "per_page": per_page,
                "entries": [e.to_dict() for e in page_entries],
            })

        elif path == "/api/stats":
            manifest = load_manifest()
            self._send_json(manifest._compute_stats())

        elif path.startswith("/api/context/"):
            image_id = path.split("/")[-1]
            manifest = load_manifest()
            entries = manifest.entries_by_image_id(image_id)
            if not entries:
                self._send_json({"error": "not found"}, 404)
                return
            entry = entries[0]
            context = _get_context(entry.doc_path, entry.line_number)
            self._send_json({
                "image_id": image_id,
                "doc_path": entry.doc_path,
                "line_number": entry.line_number,
                "context": context,
                "docs": [{"doc_path": e.doc_path, "line_number": e.line_number} for e in entries],
            })

        elif path.startswith("/image/"):
            image_id = path.split("/")[-1]
            image_path = _find_image_file(image_id)
            if image_path is None:
                self.send_error(404, f"Image not found: {image_id}")
                return
            mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
            data = image_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/approve":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            image_ids = body.get("image_ids", [])
            if not image_ids:
                self._send_json({"error": "image_ids required"}, 400)
                return

            manifest = load_manifest()
            count = 0
            for entry in manifest.entries:
                if entry.image_id in image_ids and entry.status == "downloaded":
                    entry.status = "approved"
                    count += 1
            manifest.save()
            self._send_json({"approved": count})

        elif parsed.path == "/api/set-text":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            image_id = body.get("image_id", "")
            text = body.get("text", "")
            if not image_id or not text:
                self._send_json({"error": "image_id and text required"}, 400)
                return

            manifest = load_manifest()
            count = 0
            for entry in manifest.entries:
                if entry.image_id == image_id:
                    entry.converted_text = text
                    if entry.status == "downloaded":
                        entry.status = "approved"
                    count += 1
            manifest.save()
            self._send_json({"updated": count})

        else:
            self.send_error(404)


def serve(port: int = 8765) -> None:
    """Start the viewer HTTP server."""
    server = HTTPServer(("127.0.0.1", port), ViewerHandler)
    logger.info(f"Image viewer: http://localhost:{port}")
    print(f"Image viewer running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping viewer.")
        server.shutdown()


_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>법령 이미지 뷰어 — legalize-kr</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
header { background: #1a1a2e; color: #fff; padding: 0.75rem 2rem; display: flex; justify-content: space-between; align-items: center; }
header h1 { font-size: 1.1rem; font-weight: 600; }
.stats { display: flex; gap: 0.6rem; font-size: 0.8rem; opacity: 0.9; flex-wrap: wrap; }
.stats span { background: rgba(255,255,255,0.15); padding: 0.2rem 0.5rem; border-radius: 4px; }
.controls { padding: 0.75rem 2rem; display: flex; gap: 0.75rem; align-items: center; background: #fff; border-bottom: 1px solid #ddd; flex-wrap: wrap; }
.controls select { padding: 0.4rem 0.8rem; border: 1px solid #ccc; border-radius: 4px; font-size: 0.85rem; }
.btn { padding: 0.4rem 0.9rem; border-radius: 4px; font-size: 0.85rem; cursor: pointer; border: none; }
.btn-primary { background: #1a1a2e; color: #fff; }
.btn-primary:hover { background: #16213e; }
.btn-review { background: #2563eb; color: #fff; font-weight: 600; }
.btn-review:hover { background: #1d4ed8; }
.controls-spacer { flex: 1; }

/* Grid mode */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 1rem; padding: 1.5rem 2rem; }
.card { background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.card-img { background: #fafafa; padding: 1rem; text-align: center; min-height: 80px; display: flex; align-items: center; justify-content: center; border-bottom: 1px solid #eee; }
.card-img img { max-width: 100%; max-height: 200px; }
.card-body { padding: 0.8rem 1rem; font-size: 0.8rem; }
.card-body .meta { color: #666; margin-bottom: 0.4rem; }
.card-body .meta b { color: #333; }
.card-body .context { background: #f9f9f9; padding: 0.5rem; border-radius: 4px; font-family: monospace; font-size: 0.75rem; white-space: pre-wrap; max-height: 120px; overflow-y: auto; margin: 0.4rem 0; }
.card-body .text-input { width: 100%; padding: 0.4rem; border: 1px solid #ddd; border-radius: 4px; font-size: 0.8rem; margin: 0.4rem 0; }
.card-body .actions { display: flex; gap: 0.4rem; }
.card-body .actions button { padding: 0.3rem 0.6rem; font-size: 0.75rem; border-radius: 4px; cursor: pointer; border: 1px solid #ccc; }
.btn-approve { background: #27ae60; color: #fff; border-color: #27ae60 !important; }
.btn-skip { background: #95a5a6; color: #fff; border-color: #95a5a6 !important; }
.status-badge { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 3px; font-size: 0.7rem; font-weight: 600; }
.status-extracted { background: #f0f0f0; }
.status-downloaded { background: #d4edda; color: #155724; }
.status-approved { background: #cce5ff; color: #004085; }
.status-replaced { background: #d1ecf1; color: #0c5460; }
.status-error, .status-not_found { background: #f8d7da; color: #721c24; }
.pagination { padding: 1rem 2rem; text-align: center; }
.pagination button { margin: 0 0.25rem; padding: 0.4rem 0.8rem; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; }
.no-image { color: #999; font-style: italic; }

/* Review mode */
#review-overlay {
  display: none;
  position: fixed; inset: 0; background: #111; z-index: 1000;
  flex-direction: column;
}
#review-overlay.active { display: flex; }
.review-header {
  background: #1a1a2e; color: #fff;
  padding: 0.6rem 1.5rem;
  display: flex; align-items: center; gap: 1rem; flex-shrink: 0;
}
.review-progress { font-size: 0.9rem; font-weight: 600; }
.review-id { font-size: 0.8rem; color: #94a3b8; font-family: monospace; }
.review-status-badge { font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 3px; font-weight: 600; }
.review-spacer { flex: 1; }
.review-shortcuts { font-size: 0.72rem; color: #64748b; }
kbd { background: #334155; color: #e2e8f0; padding: 0.1rem 0.35rem; border-radius: 3px; font-family: monospace; }
.btn-exit { background: #374151; color: #fff; padding: 0.3rem 0.7rem; border-radius: 4px; font-size: 0.8rem; cursor: pointer; border: none; }
.btn-exit:hover { background: #4b5563; }

.review-body {
  display: flex; flex: 1; overflow: hidden; gap: 0;
}
.review-image-panel {
  flex: 1; display: flex; align-items: center; justify-content: center;
  background: #0a0a0a; padding: 2rem; overflow: auto;
}
.review-image-panel img { max-width: 100%; max-height: 100%; object-fit: contain; }
.review-no-image { color: #555; font-style: italic; }

.review-side {
  width: 380px; flex-shrink: 0; background: #1e1e2e; color: #e2e8f0;
  display: flex; flex-direction: column; overflow: hidden;
  border-left: 1px solid #334155;
}
.review-side-section { padding: 1rem 1.2rem; border-bottom: 1px solid #2d3748; }
.review-side-section h3 { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 0.5rem; }
.review-meta-row { font-size: 0.78rem; color: #94a3b8; margin-bottom: 0.2rem; }
.review-meta-row b { color: #e2e8f0; }
.review-context {
  font-family: monospace; font-size: 0.72rem; line-height: 1.6;
  white-space: pre-wrap; background: #0f172a; padding: 0.6rem;
  border-radius: 4px; color: #94a3b8; max-height: 140px; overflow-y: auto;
}
.review-text-section { padding: 1rem 1.2rem; flex: 1; display: flex; flex-direction: column; gap: 0.6rem; }
.review-text-section h3 { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; }
#review-text {
  flex: 1; background: #0f172a; border: 1px solid #334155; border-radius: 4px;
  color: #e2e8f0; font-size: 0.82rem; padding: 0.6rem; resize: none;
  font-family: -apple-system, sans-serif; min-height: 80px;
}
#review-text:focus { outline: none; border-color: #2563eb; }
.review-actions { display: flex; gap: 0.5rem; flex-shrink: 0; }
.review-actions button {
  flex: 1; padding: 0.6rem; border-radius: 6px; font-size: 0.85rem;
  font-weight: 600; cursor: pointer; border: none; transition: opacity 0.1s;
}
.review-actions button:hover { opacity: 0.85; }
#btn-rv-approve { background: #16a34a; color: #fff; }
#btn-rv-skip { background: #374151; color: #cbd5e1; }
#btn-rv-prev { background: #1e293b; color: #94a3b8; flex: 0 0 auto; padding: 0.6rem 1rem; }
#btn-rv-next { background: #1e293b; color: #94a3b8; flex: 0 0 auto; padding: 0.6rem 1rem; }
.review-nav { display: flex; gap: 0.5rem; padding: 0 1.2rem 1rem; flex-shrink: 0; }
</style>
</head>
<body>
<header>
  <h1>법령 이미지 뷰어</h1>
  <div class="stats" id="stats"></div>
</header>
<div class="controls">
  <label>상태: <select id="filterStatus">
    <option value="">전체</option>
    <option value="extracted">extracted</option>
    <option value="downloaded">downloaded</option>
    <option value="approved">approved</option>
    <option value="replaced">replaced</option>
    <option value="not_found">not_found</option>
    <option value="error">error</option>
  </select></label>
  <label>형식: <select id="filterTag">
    <option value="">전체</option>
    <option value="src">src</option>
    <option value="id-only">id-only</option>
  </select></label>
  <button class="btn btn-primary" onclick="applyFilter()">검색</button>
  <span class="controls-spacer"></span>
  <button class="btn btn-review" onclick="startReview()">▶ 순차 리뷰</button>
</div>
<div class="grid" id="grid"></div>
<div class="pagination" id="pagination"></div>

<!-- Review overlay -->
<div id="review-overlay">
  <div class="review-header">
    <span class="review-progress" id="rv-progress">0 / 0</span>
    <span class="review-id" id="rv-id"></span>
    <span class="review-status-badge status-downloaded" id="rv-status-badge"></span>
    <span class="review-spacer"></span>
    <span class="review-shortcuts">
      <kbd>←</kbd> 이전 &nbsp;
      <kbd>→</kbd>/<kbd>Space</kbd> 다음 &nbsp;
      <kbd>A</kbd> 승인 &nbsp;
      <kbd>S</kbd> 건너뛰기 &nbsp;
      <kbd>E</kbd> 텍스트 편집
    </span>
    <button class="btn-exit" onclick="exitReview()">✕ 닫기</button>
  </div>
  <div class="review-body">
    <div class="review-image-panel" id="rv-image-panel">
      <span class="review-no-image">이미지 없음</span>
    </div>
    <div class="review-side">
      <div class="review-side-section">
        <h3>메타데이터</h3>
        <div class="review-meta-row" id="rv-doc"></div>
        <div class="review-meta-row" id="rv-priority"></div>
      </div>
      <div class="review-side-section">
        <h3>문서 컨텍스트</h3>
        <div class="review-context" id="rv-context">로딩 중…</div>
      </div>
      <div class="review-text-section">
        <h3>변환 텍스트</h3>
        <textarea id="review-text" placeholder="변환 텍스트 입력…&#10;(없으면 빈 칸으로 승인 가능)"></textarea>
      </div>
      <div class="review-nav">
        <button id="btn-rv-prev" onclick="reviewNav(-1)">← 이전</button>
        <div class="review-actions" style="flex:1">
          <button id="btn-rv-approve" onclick="reviewApprove()">승인 (A)</button>
          <button id="btn-rv-skip" onclick="reviewSkip()">건너뛰기 (S)</button>
        </div>
        <button id="btn-rv-next" onclick="reviewNav(1)">다음 →</button>
      </div>
    </div>
  </div>
</div>

<script>
// ── Grid mode ─────────────────────────────────────────────────────────────────
let currentPage = 1;
const perPage = 30;

async function loadStats() {
  const res = await fetch('/api/stats');
  const data = await res.json();
  document.getElementById('stats').innerHTML =
    Object.entries(data).map(([k, v]) => `<span>${k}: ${v}</span>`).join('');
}

function applyFilter() { loadPage(1); }

async function loadPage(page) {
  currentPage = page;
  const status = document.getElementById('filterStatus').value;
  const tag = document.getElementById('filterTag').value;
  let url = `/api/manifest?page=${page}&per_page=${perPage}`;
  if (status) url += `&status=${status}`;
  if (tag) url += `&tag_format=${tag}`;
  const res = await fetch(url);
  const data = await res.json();
  renderGrid(data.entries);
  renderPagination(data.total, page);
}

function renderGrid(entries) {
  const grid = document.getElementById('grid');
  if (!entries.length) { grid.innerHTML = '<p style="padding:2rem;color:#999;">결과 없음</p>'; return; }
  grid.innerHTML = entries.map(e => `
    <div class="card" id="card-${e.image_id}">
      <div class="card-img">
        ${['downloaded','approved','replaced'].includes(e.status)
          ? `<img src="/image/${e.image_id}" alt="${e.image_id}" loading="lazy">`
          : `<span class="no-image">이미지 없음 (${e.status})</span>`}
      </div>
      <div class="card-body">
        <div class="meta">
          <span class="status-badge status-${e.status}">${e.status}</span>
          <b>${e.image_id}</b> · ${e.tag_format}
        </div>
        <div class="meta">${e.doc_path}:${e.line_number} · 우선순위: ${e.priority}</div>
        <div class="context" id="ctx-${e.image_id}">로딩 중...</div>
        <input class="text-input" id="text-${e.image_id}" placeholder="변환 텍스트 입력..."
          value="${(e.converted_text || '').replace(/"/g, '&quot;')}">
        <div class="actions">
          <button class="btn-approve" onclick="gridApprove('${e.image_id}')">저장 + 승인</button>
          <button class="btn-skip" onclick="gridSkip('${e.image_id}')">건너뛰기</button>
        </div>
      </div>
    </div>`).join('');
  const ids = [...new Set(entries.map(e => e.image_id))];
  ids.forEach(id => loadContext(id, `ctx-${id}`));
}

async function loadContext(imageId, targetId) {
  try {
    const res = await fetch(`/api/context/${imageId}`);
    const data = await res.json();
    const el = document.getElementById(targetId);
    if (el) el.textContent = data.context || '(컨텍스트 없음)';
    return data;
  } catch(e) { return null; }
}

async function gridApprove(imageId) {
  const text = document.getElementById(`text-${imageId}`).value.trim();
  if (!text) { alert('텍스트를 입력해주세요.'); return; }
  await fetch('/api/set-text', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({image_id: imageId, text}),
  });
  loadPage(currentPage); loadStats();
}

function gridSkip(imageId) {
  const card = document.getElementById(`card-${imageId}`);
  if (card) card.style.opacity = '0.3';
}

function renderPagination(total, page) {
  const pages = Math.ceil(total / perPage);
  const el = document.getElementById('pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = '';
  if (page > 1) html += `<button onclick="loadPage(${page - 1})">이전</button>`;
  html += ` <span>${page} / ${pages} (총 ${total}건)</span> `;
  if (page < pages) html += `<button onclick="loadPage(${page + 1})">다음</button>`;
  el.innerHTML = html;
}

// ── Review mode ───────────────────────────────────────────────────────────────
let reviewEntries = [];
let reviewIndex = 0;

async function startReview() {
  const status = document.getElementById('filterStatus').value;
  const tag = document.getElementById('filterTag').value;
  let url = `/api/manifest?page=1&per_page=5000`;
  if (status) url += `&status=${status}`;
  if (tag) url += `&tag_format=${tag}`;
  const res = await fetch(url);
  const data = await res.json();
  if (!data.entries.length) { alert('표시할 항목이 없습니다.'); return; }
  reviewEntries = data.entries;
  reviewIndex = 0;
  document.getElementById('review-overlay').classList.add('active');
  renderReviewItem();
  document.addEventListener('keydown', reviewKeyHandler);
}

function exitReview() {
  document.getElementById('review-overlay').classList.remove('active');
  document.removeEventListener('keydown', reviewKeyHandler);
  loadStats(); loadPage(currentPage);
}

function renderReviewItem() {
  const e = reviewEntries[reviewIndex];
  if (!e) return;

  document.getElementById('rv-progress').textContent =
    `${reviewIndex + 1} / ${reviewEntries.length}`;
  document.getElementById('rv-id').textContent = `#${e.image_id}`;

  const badge = document.getElementById('rv-status-badge');
  badge.textContent = e.status;
  badge.className = `review-status-badge status-${e.status}`;

  document.getElementById('rv-doc').innerHTML =
    `<b>${e.doc_path}</b> 행 ${e.line_number}`;
  document.getElementById('rv-priority').innerHTML =
    `태그 형식: <b>${e.tag_format}</b> · 우선순위: <b>${e.priority}</b>`;

  document.getElementById('review-text').value = e.converted_text || '';

  // Image
  const panel = document.getElementById('rv-image-panel');
  if (['downloaded', 'approved', 'replaced'].includes(e.status)) {
    panel.innerHTML = `<img src="/image/${e.image_id}" alt="${e.image_id}">`;
  } else {
    panel.innerHTML = `<span class="review-no-image">이미지 없음 (${e.status})</span>`;
  }

  // Context (async, non-blocking)
  document.getElementById('rv-context').textContent = '로딩 중…';
  loadContext(e.image_id, 'rv-context');

  // Prev/next buttons
  document.getElementById('btn-rv-prev').disabled = reviewIndex === 0;
  document.getElementById('btn-rv-next').disabled = reviewIndex === reviewEntries.length - 1;
}

function reviewNav(delta) {
  const next = reviewIndex + delta;
  if (next < 0 || next >= reviewEntries.length) return;
  reviewIndex = next;
  renderReviewItem();
}

async function reviewApprove() {
  const e = reviewEntries[reviewIndex];
  const text = document.getElementById('review-text').value.trim();
  if (text) {
    await fetch('/api/set-text', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image_id: e.image_id, text}),
    });
  } else {
    await fetch('/api/approve', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image_ids: [e.image_id]}),
    });
  }
  // Update local entry status
  reviewEntries[reviewIndex] = {...e, status: 'approved', converted_text: text || e.converted_text};
  // Flash feedback
  const btn = document.getElementById('btn-rv-approve');
  btn.textContent = '✓ 완료';
  setTimeout(() => { btn.textContent = '승인 (A)'; }, 600);
  reviewNav(1);
}

function reviewSkip() {
  reviewNav(1);
}

function reviewKeyHandler(ev) {
  // Don't hijack keyboard when textarea is focused
  if (ev.target === document.getElementById('review-text')) {
    if (ev.key === 'Escape') ev.target.blur();
    return;
  }
  switch (ev.key) {
    case 'ArrowLeft':  ev.preventDefault(); reviewNav(-1); break;
    case 'ArrowRight':
    case ' ':          ev.preventDefault(); reviewNav(1); break;
    case 'a': case 'A': ev.preventDefault(); reviewApprove(); break;
    case 's': case 'S': ev.preventDefault(); reviewSkip(); break;
    case 'e': case 'E':
      ev.preventDefault();
      document.getElementById('review-text').focus();
      break;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
loadStats();
loadPage(1);
</script>
</body>
</html>
"""
