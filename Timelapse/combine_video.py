#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from timelapse_lib import build_video_from_directory, log_step


def run_combine_video(args: argparse.Namespace) -> int:
    log_step(
        "combine-video",
        f"Starting video combine with max_images={args.max_images}, fps={args.fps}.",
    )
    return build_video_from_directory(
        input_dir=args.input_dir,
        output_video=args.output,
        fps=args.fps,
        max_images=args.max_images,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Combine a directory of images into a video file.",
    )
    parser.add_argument("input_dir", type=Path, help="Directory to scan recursively for images.")
    parser.add_argument("output", type=Path, help="Output video file path.")
    parser.add_argument(
        "--fps",
        type=int,
        default=12,
        help="Frames per second for the output video.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Maximum number of images to process, using sorted order. Use 0 for no limit.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    start_time = time.perf_counter()
    try:
        return run_combine_video(args)
    finally:
        log_step("combine-video", f"Total runtime: {time.perf_counter() - start_time:.2f}s")


if __name__ == "__main__":
    raise SystemExit(main())
