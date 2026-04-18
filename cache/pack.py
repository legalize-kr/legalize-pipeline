"""Pack a cache snapshot into a manifest JSON and Markdown summary."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _human_bytes(n: int) -> str:
    """Convert bytes to human-readable string with 2 decimal places."""
    for exp, unit in enumerate(("B", "KB", "MB", "GB", "TB")):
        boundary = 1024 ** (exp + 1)
        if n < boundary or unit == "TB":
            value = n / (1024 ** exp)
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}"
    return str(n)


def collect_parts(staging: Path) -> list[dict]:
    """Collect all files in staging dir, compute sha256, sorted by name."""
    parts = []
    if not staging.exists():
        return parts
    for p in sorted(staging.iterdir()):
        if p.is_file():
            parts.append({
                "filename": p.name,
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size,
            })
    return parts


def collect_files(cache_root: Path) -> tuple[list[dict], dict]:
    """Walk cache_root, return (files[], subdirs{}) with per-top-level-subdir aggregation."""
    known_subdirs = ("detail", "history", "precedent", "images")
    subdirs: dict[str, dict] = {k: {"file_count": 0, "bytes": 0} for k in known_subdirs}
    files = []

    if not cache_root.exists():
        return files, subdirs

    for entry in sorted(cache_root.rglob("*")):
        if not entry.is_file():
            continue
        rel = entry.relative_to(cache_root)
        rel_posix = rel.as_posix()
        size = entry.stat().st_size
        files.append({
            "path": rel_posix,
            "sha256": sha256_file(entry),
            "bytes": size,
        })
        # Aggregate into top-level subdir bucket
        top = rel.parts[0] if rel.parts else ""
        if top in subdirs:
            subdirs[top]["file_count"] += 1
            subdirs[top]["bytes"] += size

    return files, subdirs


def git_head(repo_path: Path) -> str | None:
    """Return HEAD SHA for repo_path, or None on any failure."""
    if not repo_path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def collect_source_commits(cache_root: Path) -> dict:
    pipeline_root = Path(__file__).resolve().parents[1]
    workspace_root = cache_root.parent  # parent of .cache/

    return {
        "legalize-pipeline": git_head(pipeline_root),
        "legalize-kr": git_head(workspace_root),
        "precedent-kr": git_head(workspace_root.parent / "precedent-kr"),
    }


def build_manifest(
    schema_version: str,
    created_at: str,
    source_commits: dict,
    parts: list[dict],
    files: list[dict],
    subdirs: dict,
) -> dict:
    total_bytes = sum(f["bytes"] for f in files)
    total_files = len(files)
    parts_bytes = sum(p["bytes"] for p in parts)

    return {
        "schema_version": schema_version,
        "created_at_utc": created_at,
        "decompress_command": "zstd -d --long=27 -T0",
        "min_zstd_version": "1.4.4",
        "decoder_window_mb": 128,
        "source_commits": source_commits,
        "parts": parts,
        "files": files,
        "subdirs": subdirs,
        "totals": {
            "bytes": total_bytes,
            "file_count": total_files,
            "parts_count": len(parts),
            "parts_bytes": parts_bytes,
        },
    }


def write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def render_markdown(manifest: dict, date_str: str) -> str:
    t = manifest["totals"]
    sc = manifest["source_commits"]
    subdirs = manifest["subdirs"]
    parts = manifest["parts"]
    created_at = manifest["created_at_utc"]
    date_compact = date_str.replace("-", "")
    tag = f"cache-{date_compact}"

    lines = [
        f"# 캐시 스냅샷 {date_str}",
        "",
        f"_전체 데이터를 다운로드하는 데 시간이 제법 걸려 `.cache/` 디렉토리를 압축하여 공유합니다._  ",
        f"_{date_str} 기준, "
        + ", ".join(
            f"{stats['file_count']:,}개 {subdir}"
            for subdir, stats in subdirs.items()
            if stats["file_count"] > 0
        )
        + f"을 포함합니다. (비압축 {_human_bytes(t['bytes'])}, {t['parts_count']}개 파트)_",
        "",
        "## 사용 준비",
        "",
        "### 1. 파트 파일 다운로드",
        "",
        "아래 **Release assets** 섹션에서 `" + tag + ".tar.zst.part*` 파일을 모두 받으세요.",
        "sha256 체크섬으로 무결성을 확인하는 것을 권장합니다.",
        "",
        "### 2. 압축 해제",
        "",
        "`zstd >= 1.4.4` 및 `--long=27` 옵션(128 MB 디코더 윈도우)이 필요합니다.",
        "",
        "```sh",
        f"# 모든 파트를 한 번에 해제하여 워크스페이스 루트에 풀기",
        f"cat {tag}.tar.zst.part* | zstd -d --long=27 -T0 | tar -xf -",
        "# .cache/detail/, .cache/history/, .cache/precedent/, .cache/images/ 가 생성됩니다",
        "```",
        "",
        "> **주의:** 파트 파일 중 하나라도 누락되면 압축 해제가 실패합니다.",
        "> zstd 롱레인지 디코더는 누락된 청크를 건너뛸 수 없으므로, 실패한 파트를 먼저 재다운로드하세요.",
        "",
        "### 3. 캐시를 이용한 작업",
        "",
        "```sh",
        "# 캐시 기반 전체 법령 import (API 호출 없음)",
        "cd legalize-pipeline",
        "python -m laws.import_laws --from-cache",
        "",
        "# 캐시 기반 전체 판례 변환 (API 호출 없음)",
        "python -m precedents.import_precedents",
        "",
        "# 최신 법령 증분 업데이트 (API 키 필요)",
        "LAW_OC=your-api-key python -m laws.update --days 7",
        "```",
        "",
        "> [국가법령정보센터 OpenAPI](https://open.law.go.kr)에서 API 키(`LAW_OC`)를 발급받아야 합니다.",
        "",
        "## 캐시 구조",
        "",
        "```",
        ".cache/",
        "  detail/{MST}.xml             # 법령 상세 API 원본 XML",
        "  history/{법령명}.json         # 법령별 개정 이력",
        "  precedent/{판례일련번호}.xml  # 판례 상세 API 원본 XML",
        "  images/                       # 법령 이미지",
        "```",
        "",
        "## 통계",
        "",
        "| 디렉토리 | 파일 수 | 크기 |",
        "|---|---:|---:|",
    ]

    for subdir, stats in subdirs.items():
        lines.append(
            f"| `{subdir}` | {stats['file_count']:,} | {_human_bytes(stats['bytes'])} |"
        )

    lines += [
        f"| **합계** | **{t['file_count']:,}** | **{_human_bytes(t['bytes'])}** |",
        "",
        "## Source commits",
        "",
        "| Repository | Commit |",
        "|---|---|",
    ]

    for repo, commit in sc.items():
        commit_str = f"`{commit}`" if commit else "N/A"
        lines.append(f"| {repo} | {commit_str} |")

    lines += [
        "",
        "## Release assets",
        "",
        f"압축 파트 {t['parts_count']}개 + `manifest.json` + `manifest.md`",
        "",
        "| Filename | Bytes | sha256 |",
        "|---|---:|---|",
    ]

    for p in parts:
        lines.append(f"| `{p['filename']}` | {p['bytes']:,} | `{p['sha256']}` |")

    lines += ["", f"_Generated at {created_at}_", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack cache snapshot into manifest + markdown.")
    parser.add_argument("--staging", required=True, help="Dir containing tar parts")
    parser.add_argument("--cache-root", required=True, help="The .cache/ dir to walk")
    parser.add_argument("--manifest", required=True, help="Output JSON path")
    parser.add_argument("--markdown", required=True, help="Output MD path")
    parser.add_argument("--schema-version", default="1", help="Manifest schema version")
    args = parser.parse_args()

    staging = Path(args.staging)
    cache_root = Path(args.cache_root)
    manifest_path = Path(args.manifest)
    markdown_path = Path(args.markdown)

    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y-%m-%d")

    parts = collect_parts(staging)
    files, subdirs = collect_files(cache_root)
    source_commits = collect_source_commits(cache_root)

    manifest = build_manifest(
        schema_version=args.schema_version,
        created_at=created_at,
        source_commits=source_commits,
        parts=parts,
        files=files,
        subdirs=subdirs,
    )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))

    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(markdown_path, render_markdown(manifest, date_str))

    print(f"Manifest: {manifest_path}")
    print(f"Markdown: {markdown_path}")
    print(f"Parts: {len(parts)}, Files: {len(files)}")


if __name__ == "__main__":
    main()
