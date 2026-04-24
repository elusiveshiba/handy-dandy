#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from timelapse_lib import (
    extract_colour_images,
    log_step,
    print_extraction_summary,
    validate_percent,
)


def run_colour_filter(args: argparse.Namespace) -> int:
    colour_pixel_ratio = validate_percent(
        "colour pixel ratio percent",
        args.colour_pixel_ratio_percent,
    )
    log_step(
        "colour-filter",
        f"Starting extraction with max_images={args.max_images}, "
        f"channel_delta={args.channel_delta}, "
        f"minimum_colour={args.colour_pixel_ratio_percent:.2f}%.",
    )
    stats = extract_colour_images(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        sample_size=args.sample_size,
        channel_delta=args.channel_delta,
        colour_pixel_ratio=colour_pixel_ratio,
        max_images=args.max_images,
        workers=args.workers,
    )
    print_extraction_summary(stats, args.output_dir)
    return 0 if stats.failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy only colour images from an input directory to an output directory.",
    )
    parser.add_argument("input_dir", type=Path, help="Directory to scan recursively for images.")
    parser.add_argument("output_dir", type=Path, help="Directory where colour images are copied.")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=512,
        help="Longest edge used while checking whether an image is colour.",
    )
    parser.add_argument(
        "--channel-delta",
        type=int,
        default=10,
        help="Minimum RGB channel difference that counts as colour in a pixel.",
    )
    parser.add_argument(
        "--colour-pixel-ratio-percent",
        type=float,
        default=0.5,
        help="Minimum percentage of pixels that must show colour for an image to be kept.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Maximum number of images to process, using sorted order. Use 0 for no limit.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads to use for image classification.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    start_time = time.perf_counter()
    try:
        return run_colour_filter(args)
    finally:
        log_step("colour-filter", f"Total runtime: {time.perf_counter() - start_time:.2f}s")


if __name__ == "__main__":
    raise SystemExit(main())
