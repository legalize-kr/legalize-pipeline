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

    lines = [
        f"# Cache Snapshot {date_str}",
        "",
        f"Generated at {created_at}.",
        "",
        "## Summary",
        "",
        f"- Total uncompressed size: {_human_bytes(t['bytes'])}",
        f"- Total file count: {t['file_count']:,}",
        f"- Compressed parts: {t['parts_count']} parts, {_human_bytes(t['parts_bytes'])}",
        "",
        "## Per-subdirectory counts",
        "",
        "| Subdir | Files | Bytes |",
        "|---|---:|---:|",
    ]

    for subdir, stats in subdirs.items():
        lines.append(
            f"| {subdir} | {stats['file_count']:,} | {_human_bytes(stats['bytes'])} |"
        )

    # Determine date for the cat command example
    date_compact = date_str.replace("-", "")
    lines += [
        "",
        "## Decompression",
        "",
        "Requires `zstd >= 1.4.4` with `--long=27` (128 MB decoder window).",
        "",
        "```sh",
        f"cat cache-{date_compact}.tar.zst.part* | zstd -d --long=27 -T0 | tar -xf -",
        "```",
        "",
        "> ⚠ **Missing parts cannot be skipped.** Re-download any failed part before piping into zstd; the long-range decoder cannot resync past a missing chunk.",
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
        "| Filename | Bytes | sha256 |",
        "|---|---:|---|",
    ]

    for p in parts:
        lines.append(f"| {p['filename']} | {p['bytes']:,} | `{p['sha256']}` |")

    lines.append("")
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
