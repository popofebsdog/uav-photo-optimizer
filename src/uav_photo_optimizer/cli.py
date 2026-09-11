"""Local reports and exclusive, streaming copy of the selected files."""

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import load_config
from .metadata import apply_heights, discover, scan
from .selection import select
from .terrain import apply_dsm


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path else None


def checked_source(root, photo):
    path = root / photo.relative_path
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f"source path changed: {photo.relative_path}")
    stat = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (photo.size_bytes, photo.mtime_ns):
        raise ValueError(f"source changed since scan: {photo.relative_path}")
    return path


def copy_selected(root, output, photos):
    copied = []
    for photo in photos:
        if photo.decision == "SKIP":
            continue
        source = checked_source(root, photo)
        target = output / "selected" / photo.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with source.open("rb") as src, target.open("xb") as dst:
            while block := src.read(1024 * 1024):
                digest.update(block)
                dst.write(block)
        checked_source(root, photo)
        if target.stat().st_size != photo.size_bytes:
            raise OSError(f"copy size mismatch: {photo.relative_path}")
        copied.append({"photo_id": photo.photo_id, "relative_path": photo.relative_path, "size_bytes": photo.size_bytes, "sha256": digest.hexdigest()})
    return copied


def csv_cell(value):
    # Prevent untrusted filenames/metadata from becoming spreadsheet formulas.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def run(args):
    started = time.monotonic()
    root = args.input.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("input must be a directory")
    output = args.output.resolve()
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("output must be separate from input (neither may contain the other)")
    if output.exists():
        raise ValueError("output already exists; choose a new directory to avoid overwriting a prior run")
    config = load_config(args.config)
    if args.min_overlap is not None:
        config = replace(config, min_retained_forward_overlap=args.min_overlap)
    if (config.require_dsm or config.height_mode == "gps_minus_dsm_trial") and args.dsm is None:
        raise ValueError("this configuration requires --dsm")
    photos, ignored = discover(root)
    if not photos:
        raise ValueError("no supported photos found")
    print(f"Scanning {len(photos)} photos…", file=sys.stderr)
    exiftool_version = scan(root, photos, config)
    apply_heights(photos, args.heights)
    dsm_info = apply_dsm(photos, args.dsm, config) if args.dsm else None
    triggers = select(photos, config, args.force)
    selected = [p for p in photos if p.decision != "SKIP"]
    raw_bytes = sum(p.size_bytes for p in photos)
    selected_bytes = sum(p.size_bytes for p in selected)
    summary = {
        "session_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
        "algorithm_version": __version__, "exiftool_version": exiftool_version,
        "config_snapshot": config.snapshot(), "height_csv_sha256": fingerprint(args.heights),
        "result_classification": {
            "gps_proxy_trial": "EXPERIMENTAL_GPS_PROXY",
            "gps_minus_dsm_trial": "EXPERIMENTAL_GPS_MINUS_DSM_UNCONFIRMED_VERTICAL_DATUM",
        }.get(config.height_mode, "METADATA_GEOMETRY_ONLY"),
        "height_assumption": {
            "gps_proxy_trial": "GPS altitude used as footprint height; not measured AGL; actual overlap unverified",
            "gps_minus_dsm_trial": "Estimated AGL = GPS altitude - DSM center elevation; vertical datum compatibility is unconfirmed; actual overlap unverified",
        }.get(config.height_mode, "explicit AGL evidence required"),
        "dsm": dsm_info,
        "dsm_status_counts": dict(Counter(p.dsm_status for p in photos)),
        **triggers, "raw_photo_count": len(photos), "selected_photo_count": len(selected),
        "skipped_photo_count": len(photos) - len(selected), "raw_total_size_bytes": raw_bytes,
        "selected_total_size_bytes": selected_bytes, "skipped_total_size_bytes": raw_bytes - selected_bytes,
        "photo_reduction_ratio": 1 - len(selected) / len(photos),
        "storage_reduction_ratio": 1 - selected_bytes / raw_bytes if raw_bytes else 0,
        "restored_photo_count": sum(p.restored for p in photos), "ignored_file_count": ignored,
        "decision_counts": dict(Counter(p.decision for p in photos)),
        "camera_models": dict(Counter(p.model or "UNKNOWN" for p in photos)),
        "metadata_available_counts": {
            "capture_time": sum(p.timestamp is not None for p in photos),
            "gps": sum(p.latitude is not None and p.longitude is not None for p in photos),
            "explicit_agl": sum(p.agl_m is not None for p in photos),
            "normalized_pitch_yaw": sum(p.pitch is not None and p.yaw is not None for p in photos),
        },
        "reason_counts": dict(Counter(r for p in photos for r in set(p.reasons))),
        "retained_link_counts": dict(Counter(p.retained_link_status for p in photos if p.decision != "SKIP")),
        "side_overlap_status": "NOT_IMPLEMENTED", "coverage_status": "NOT_EVALUATED",
        "modeling_validation_status": "NOT_RUN", "copy_requested": args.copy,
        "analysis_duration_seconds": round(time.monotonic() - started, 3),
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "summary.json", summary)
    write_json(output / "manifest.json", [asdict(p) for p in photos])
    write_json(output / "selected-files.json", [p.relative_path for p in selected])
    with (output / "manifest.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(photos[0])))
        writer.writeheader()
        for photo in photos:
            row = asdict(photo)
            row["reasons"] = ";".join(photo.reasons)
            writer.writerow({key: csv_cell(value) for key, value in row.items()})
    if args.copy:
        try:
            if shutil.disk_usage(output).free < selected_bytes:
                raise OSError("insufficient free space for selected photos")
            copies = copy_selected(root, output, photos)
            write_json(output / "copy-result.json", {"status": "COMPLETE", "files": copies})
        except (OSError, ValueError) as error:
            write_json(output / "copy-result.json", {"status": "FAILED", "message": str(error), "note": "Partial copies retained; use a new output directory for retry."})
            raise
    print(json.dumps({"selected": len(selected), "skipped": len(photos) - len(selected), "report": str(output), "copied": args.copy}, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="UAV metadata optimizer: reports by default; source files are never deleted.")
    parser.add_argument("input", type=Path, help="source photo directory (recursive)")
    parser.add_argument("--output", type=Path, required=True, help="new report/output directory outside source")
    parser.add_argument("--config", type=Path, help="JSON config; defaults include 80%% minimum overlap")
    parser.add_argument("--heights", type=Path, help="CSV: relative_path,agl_m,source; explicit per-image height above ground")
    parser.add_argument("--dsm", type=Path, help="projected metre-unit GeoTIFF for local slope/relief protection; does not infer vertical datum")
    parser.add_argument("--min-overlap", type=float, help="minimum retained overlap as fraction, e.g. 0.8 or 0.6")
    parser.add_argument("--force", action="store_true", help="run selection below 3 GB / 1000 images; does not bypass safety checks")
    parser.add_argument("--copy", action="store_true", help="copy selected photos to output/selected; preserves relative paths")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
