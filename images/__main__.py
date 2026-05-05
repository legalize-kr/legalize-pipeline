"""CLI entry point for the images pipeline.

Usage:
    python -m images [--cache-dir DIR] [--output-dir DIR] extract
    python -m images download [--workers N] [--verify]
    python -m images report [--format tsv|stats] [--status STATUS] [--output FILE]
    python -m images approve --ids 123,456 | --doc-path "kr/민법/*"
    python -m images replace [--dry-run]
    python -m images stats
    python -m images viewer [--port PORT]
"""

import argparse
import logging
from pathlib import Path

from .config import CONCURRENT_WORKERS


def main():
    parser = argparse.ArgumentParser(description="Images pipeline for legalize-kr")

    # Global options
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Override image cache directory (default: LEGALIZE_CACHE_DIR/images or WORKSPACE_ROOT/.cache/images)",
    )
    parser.add_argument(
        "--kr-dir",
        type=Path,
        help="Override markdown source directory (default: LEGALIZE_KR_REPO/kr or WORKSPACE_ROOT/legalize-kr/kr)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override output directory for reports and viewer export",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract
    subparsers.add_parser("extract", help="Scan markdown files and build image manifest")

    # download
    dl = subparsers.add_parser("download", help="Download images from law.go.kr")
    dl.add_argument(
        "--workers",
        type=int,
        default=CONCURRENT_WORKERS,
        help=f"Number of concurrent workers (default: {CONCURRENT_WORKERS})",
    )
    dl.add_argument(
        "--verify",
        action="store_true",
        help="Re-verify checksums for already-downloaded images",
    )

    # report
    rp = subparsers.add_parser("report", help="Print image pipeline report")
    rp.add_argument(
        "--format",
        choices=["tsv", "stats"],
        default="stats",
        help="Output format (default: stats)",
    )
    rp.add_argument(
        "--status",
        help="Filter by status (e.g. downloaded, extracted)",
    )
    rp.add_argument(
        "--doc-path",
        help='Filter by document path glob (e.g. "kr/민법/*")',
    )
    rp.add_argument(
        "--output",
        help="Write report to file instead of stdout",
    )

    # approve
    ap = subparsers.add_parser("approve", help="Approve entries for text replacement")
    ap_group = ap.add_mutually_exclusive_group(required=True)
    ap_group.add_argument(
        "--ids",
        help="Comma-separated image IDs to approve",
    )
    ap_group.add_argument(
        "--doc-path",
        help='Glob pattern for document paths to approve (e.g. "kr/민법/*")',
    )

    # replace
    rep = subparsers.add_parser("replace", help="Replace image references with converted text")
    rep.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview replacements without writing files",
    )

    # stats
    subparsers.add_parser("stats", help="Print quick status summary")

    # viewer
    vw = subparsers.add_parser("viewer", help="Launch image review viewer")
    vw.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the viewer server (default: 8765)",
    )

    # upload
    up = subparsers.add_parser("upload", help="Upload cached images to Cloudflare R2")
    up.add_argument("--workers", type=int, default=5, help="Concurrent upload threads (default: 5)")
    up.add_argument("--limit", type=int, default=None, help="Max files to upload (testing)")
    up.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    up.add_argument("--only-approved", action="store_true", help="Upload only approved/replaced images")

    # export
    exp = subparsers.add_parser("export", help="Export manifest to web-viewer JSON")
    exp.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path (file for legacy, directory for --sharded)",
    )
    exp.add_argument(
        "--all-statuses",
        action="store_true",
        help="Include all statuses including error and not_found",
    )
    exp.add_argument(
        "--sharded",
        action="store_true",
        help="Produce sharded output (manifest.json + list-*.json + shard-*.json)",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Apply global directory overrides before any subcommand runs
    if args.cache_dir:
        from .config import set_cache_dir
        set_cache_dir(args.cache_dir.resolve())
    if args.kr_dir:
        from .config import set_kr_dir
        set_kr_dir(args.kr_dir.resolve())

    if args.command == "extract":
        from .extract import extract
        extract()

    elif args.command == "download":
        if args.verify:
            from .download import verify_checksums
            verify_checksums()
        else:
            from .download import download_images
            download_images(workers=args.workers)

    elif args.command == "report":
        from .report import generate_report
        if args.output:
            output = Path(args.output)
        elif args.output_dir:
            output = args.output_dir.resolve() / f"report.{args.format}"
        else:
            output = None
        generate_report(format=args.format, status=args.status, doc_path=args.doc_path, output=output)

    elif args.command == "approve":
        from .replace import approve_images
        if args.ids:
            image_ids = [i.strip() for i in args.ids.split(",")]
            approve_images(image_ids=image_ids)
        else:
            approve_images(doc_path=args.doc_path)

    elif args.command == "replace":
        from .replace import replace_images
        replace_images(dry_run=args.dry_run)

    elif args.command == "stats":
        from .report import print_stats
        print_stats()

    elif args.command == "viewer":
        from .viewer import serve
        serve(port=args.port)

    elif args.command == "export":
        statuses = None if args.all_statuses else {"extracted", "downloaded", "approved", "replaced", "skipped"}
        if args.sharded:
            from .export import export_sharded
            count = export_sharded(output_dir=args.output.resolve(), include_statuses=statuses)
            print(f"Exported {count} images (sharded) → {args.output}")
        else:
            from .export import export_images
            count = export_images(output=args.output.resolve(), include_statuses=statuses)
            print(f"Exported {count} images → {args.output}")

    elif args.command == "upload":
        from .upload import upload_images
        counts = upload_images(
            workers=args.workers,
            limit=args.limit,
            dry_run=args.dry_run,
            only_approved=args.only_approved,
        )
        prefix = "DRY RUN — " if args.dry_run else ""
        upload_count = counts.get("would-upload", 0) if args.dry_run else counts.get("uploaded", 0)
        print(
            f"{prefix}Upload complete: "
            f"uploaded={upload_count} "
            f"skipped={counts.get('skipped', 0)} "
            f"errors={counts.get('error', 0)}"
        )


if __name__ == "__main__":
    main()
