#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from timelapse_lib import (
    IMAGE_SORT_MODES,
    filter_images,
    log_step,
    print_filter_summary,
    validate_percent,
)


def run_difference_filter(args: argparse.Namespace) -> int:
    change_threshold = validate_percent(
        "change threshold percent",
        args.change_threshold_percent,
    )
    log_step(
        "difference-filter",
        f"Starting difference filter with max_images={args.max_images}, "
        f"sort_by={args.sort_by}, "
        f"pixel_delta={args.pixel_delta}, "
        f"change_threshold={args.change_threshold_percent:.2f}%.",
    )
    _, stats = filter_images(
        input_dir=args.input_dir,
        filtered_dir=args.output_dir,
        comparison_size=args.comparison_size,
        pixel_delta=args.pixel_delta,
        change_threshold=change_threshold,
        max_images=args.max_images,
        prefilter_size=args.prefilter_size,
        prefilter_band=validate_percent(
            "prefilter band percent",
            args.prefilter_band_percent,
        ),
        sort_by=args.sort_by,
        workers=args.workers,
    )
    print_filter_summary(stats, args.output_dir)
    return 0 if stats.failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy only meaningfully changed images from an input directory to an output directory.",
    )
    parser.add_argument("input_dir", type=Path, help="Directory to scan recursively for images.")
    parser.add_argument("output_dir", type=Path, help="Directory where filtered images are copied.")
    parser.add_argument(
        "--comparison-size",
        type=int,
        default=320,
        help="Square size used while comparing frames.",
    )
    parser.add_argument(
        "--pixel-delta",
        type=int,
        default=12,
        help="Minimum grayscale difference that counts as a changed pixel.",
    )
    parser.add_argument(
        "--change-threshold-percent",
        type=float,
        default=5.0,
        help="Minimum percentage of changed pixels required to keep a frame.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Maximum number of images to process after sorting. Use 0 for no limit.",
    )
    parser.add_argument(
        "--sort-by",
        choices=IMAGE_SORT_MODES,
        default="filename",
        help="Sort images by filename, date taken, or date modified.",
    )
    parser.add_argument(
        "--prefilter-size",
        type=int,
        default=64,
        help="Square size used for the fast duplicate prefilter. Use 0 to disable it.",
    )
    parser.add_argument(
        "--prefilter-band-percent",
        type=float,
        default=1.0,
        help="Safety band around the change threshold before the full comparison is used.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads to use for frame preprocessing.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    start_time = time.perf_counter()
    try:
        return run_difference_filter(args)
    finally:
        log_step(
            "difference-filter",
            f"Total runtime: {time.perf_counter() - start_time:.2f}s",
        )


if __name__ == "__main__":
    raise SystemExit(main())
