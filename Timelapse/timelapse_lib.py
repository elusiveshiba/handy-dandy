#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
PIPELINE_STEPS = ("colour-filter", "difference-filter", "combine-video")


@dataclass
class ExtractionStats:
    scanned: int = 0
    copied: int = 0
    skipped_grayscale: int = 0
    failed: int = 0


@dataclass
class FilterStats:
    scanned: int = 0
    kept: int = 0
    skipped_similar: int = 0
    failed: int = 0


def log_step(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def describe_path(path: Path, base_dir: Path | None = None) -> str:
    if base_dir is not None:
        try:
            return str(path.relative_to(base_dir))
        except ValueError:
            pass
    return str(path)


def format_ratio(value: float) -> str:
    return f"{value * 100:.2f}%"


def require_pillow():
    try:
        from PIL import Image, ImageChops, ImageFile, ImageOps
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: Pillow. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        ) from exc

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    return Image, ImageChops, ImageOps


def require_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: numpy. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        ) from exc

    return np


def require_video_dependencies():
    try:
        import imageio.v2 as imageio
    except ImportError as exc:
        raise SystemExit(
            "Missing video dependencies. Install dependencies with "
            "`python3 -m pip install -r requirements.txt`."
        ) from exc

    np = require_numpy()
    return imageio, np


def validate_percent(name: str, value: float) -> float:
    if not 0 <= value <= 100:
        raise SystemExit(f"{name} must be between 0 and 100. Received {value}.")
    return value / 100.0


def iter_image_paths(input_dir: Path, max_images: int | None = None) -> list[Path]:
    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    image_paths = sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if max_images is None or max_images <= 0:
        return image_paths
    return image_paths[:max_images]


def output_path_for(source_path: Path, input_root: Path, output_root: Path) -> Path:
    relative_path = source_path.relative_to(input_root)
    destination = output_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def normalize_prefilter_size(prefilter_size: int | None, comparison_size: int) -> int:
    if prefilter_size is None or prefilter_size <= 0:
        return 0
    return min(prefilter_size, comparison_size)


def safe_worker_count(requested_workers: int | None, item_count: int) -> int:
    if requested_workers is None or requested_workers <= 1:
        return 1
    return max(1, min(requested_workers, item_count))


def format_elapsed(seconds: float) -> str:
    return f"{seconds:.2f}s"


def is_colour_image(
    image_path: Path,
    sample_size: int,
    channel_delta: int,
    colour_pixel_ratio: float,
) -> tuple[bool, float]:
    Image, _, ImageOps = require_pillow()
    np = require_numpy()

    with Image.open(image_path) as image:
        rgb_image = ImageOps.exif_transpose(image).convert("RGB")
        rgb_image.thumbnail((sample_size, sample_size))

        rgb_array = np.asarray(rgb_image, dtype=np.int16)

    max_diff = np.maximum.reduce(
        [
            np.abs(rgb_array[:, :, 0] - rgb_array[:, :, 1]),
            np.abs(rgb_array[:, :, 0] - rgb_array[:, :, 2]),
            np.abs(rgb_array[:, :, 1] - rgb_array[:, :, 2]),
        ]
    )
    detected_colour_ratio = float(np.count_nonzero(max_diff >= channel_delta)) / max(
        1, max_diff.size
    )
    return detected_colour_ratio >= colour_pixel_ratio, detected_colour_ratio


def classify_colour_image(
    image_path: Path,
    sample_size: int,
    channel_delta: int,
    colour_pixel_ratio: float,
) -> tuple[bool, float]:
    return is_colour_image(
        image_path=image_path,
        sample_size=sample_size,
        channel_delta=channel_delta,
        colour_pixel_ratio=colour_pixel_ratio,
    )


def classify_colour_image_worker(
    task: tuple[Path, int, int, float],
) -> tuple[Path, bool, float | None, str | None]:
    image_path, sample_size, channel_delta, colour_pixel_ratio = task
    try:
        is_colour, detected_colour_ratio = classify_colour_image(
            image_path=image_path,
            sample_size=sample_size,
            channel_delta=channel_delta,
            colour_pixel_ratio=colour_pixel_ratio,
        )
        return image_path, is_colour, detected_colour_ratio, None
    except Exception as exc:
        return image_path, False, None, str(exc)


def extract_colour_images(
    input_dir: Path,
    output_dir: Path,
    sample_size: int,
    channel_delta: int,
    colour_pixel_ratio: float,
    max_images: int | None,
    workers: int = 1,
) -> ExtractionStats:
    stats = ExtractionStats()
    image_paths = iter_image_paths(input_dir, max_images=max_images)
    total_images = len(image_paths)
    worker_count = safe_worker_count(workers, total_images)

    log_step(
        "colour-filter",
        f"Found {total_images} images in {input_dir}. Copying colour images to {output_dir} "
        f"with workers={worker_count}.",
    )

    if worker_count == 1:
        results = (
            classify_colour_image_worker(
                (image_path, sample_size, channel_delta, colour_pixel_ratio)
            )
            for image_path in image_paths
        )
    else:
        tasks = [
            (image_path, sample_size, channel_delta, colour_pixel_ratio)
            for image_path in image_paths
        ]
        executor = ThreadPoolExecutor(max_workers=worker_count)
        results = executor.map(classify_colour_image_worker, tasks)

    try:
        for index, (image_path, is_colour, detected_colour_ratio, error_message) in enumerate(
            results, start=1
        ):
            stats.scanned += 1
            if error_message is not None or detected_colour_ratio is None:
                stats.failed += 1
                print(
                    f"[colour-filter] Failed to process {image_path}: {error_message}",
                    file=sys.stderr,
                )
                continue

            try:
                if is_colour:
                    destination = output_path_for(image_path, input_dir, output_dir)
                    shutil.copy2(image_path, destination)
                    stats.copied += 1
                    log_step(
                        "colour-filter",
                        f"[{index}/{total_images}] Copied colour image "
                        f"({format_ratio(detected_colour_ratio)} colour pixels): "
                        f"{describe_path(image_path, input_dir)} -> "
                        f"{describe_path(destination, output_dir)}",
                    )
                else:
                    stats.skipped_grayscale += 1
                    log_step(
                        "colour-filter",
                        f"[{index}/{total_images}] Skipped grayscale image "
                        f"({format_ratio(detected_colour_ratio)} colour pixels): "
                        f"{describe_path(image_path, input_dir)}",
                    )
            except Exception as exc:
                stats.failed += 1
                print(f"[colour-filter] Failed to process {image_path}: {exc}", file=sys.stderr)
    finally:
        if worker_count > 1:
            executor.shutdown()

    return stats


def load_grayscale_frame(image_path: Path, target_size: int):
    Image, _, ImageOps = require_pillow()
    np = require_numpy()

    with Image.open(image_path) as image:
        grayscale = ImageOps.exif_transpose(image).convert("L")
        resized = grayscale.resize((target_size, target_size))
        return np.asarray(resized, dtype=np.uint8).copy()


def prepare_difference_frame(
    image_path: Path,
    comparison_size: int,
    prefilter_size: int,
) -> tuple[object, object | None]:
    normalized_prefilter_size = normalize_prefilter_size(prefilter_size, comparison_size)

    comparison_frame = load_grayscale_frame(image_path, comparison_size)
    prefilter_frame = (
        load_grayscale_frame(image_path, normalized_prefilter_size)
        if normalized_prefilter_size > 0
        else None
    )

    return comparison_frame, prefilter_frame


def prepare_difference_frame_worker(
    task: tuple[Path, int, int],
) -> tuple[Path, object | None, object | None, str | None]:
    image_path, comparison_size, prefilter_size = task
    try:
        comparison_frame, prefilter_frame = prepare_difference_frame(
            image_path=image_path,
            comparison_size=comparison_size,
            prefilter_size=prefilter_size,
        )
        return image_path, comparison_frame, prefilter_frame, None
    except Exception as exc:
        return image_path, None, None, str(exc)


def changed_pixel_ratio(previous_frame, current_frame, pixel_delta: int) -> float:
    np = require_numpy()
    diff = np.abs(current_frame.astype(np.int16) - previous_frame.astype(np.int16))
    changed_pixels = int(np.count_nonzero(diff >= pixel_delta))
    total_pixels = max(1, current_frame.size)
    return changed_pixels / total_pixels


def filter_images(
    input_dir: Path,
    filtered_dir: Path,
    comparison_size: int,
    pixel_delta: int,
    change_threshold: float,
    max_images: int | None,
    prefilter_size: int = 0,
    prefilter_band: float = 0.0,
    workers: int = 1,
) -> tuple[list[Path], FilterStats]:
    stats = FilterStats()
    kept_paths: list[Path] = []
    previous_kept_frame = None
    previous_prefilter_frame = None
    image_paths = iter_image_paths(input_dir, max_images=max_images)
    total_images = len(image_paths)
    worker_count = safe_worker_count(workers, total_images)
    normalized_prefilter_size = normalize_prefilter_size(prefilter_size, comparison_size)

    log_step(
        "difference-filter",
        f"Found {total_images} images in {input_dir}. Copying kept frames to "
        f"{filtered_dir} with a {format_ratio(change_threshold)} change threshold, "
        f"prefilter_size={normalized_prefilter_size}, workers={worker_count}.",
    )

    if worker_count == 1:
        prepared_frames = (
            prepare_difference_frame_worker(
                (image_path, comparison_size, normalized_prefilter_size)
            )
            for image_path in image_paths
        )
    else:
        tasks = [
            (image_path, comparison_size, normalized_prefilter_size)
            for image_path in image_paths
        ]
        executor = ThreadPoolExecutor(max_workers=worker_count)
        prepared_frames = executor.map(prepare_difference_frame_worker, tasks)

    try:
        for index, (
            image_path,
            comparison_frame,
            prefilter_frame,
            error_message,
        ) in enumerate(prepared_frames, start=1):
            stats.scanned += 1
            if error_message is not None or comparison_frame is None:
                stats.failed += 1
                print(
                    f"[difference-filter] Failed to process {image_path}: {error_message}",
                    file=sys.stderr,
                )
                continue

            if previous_kept_frame is None:
                keep_image = True
                change_ratio = None
            else:
                skip_via_prefilter = False
                if prefilter_frame is not None and previous_prefilter_frame is not None:
                    prefilter_ratio = changed_pixel_ratio(
                        previous_frame=previous_prefilter_frame,
                        current_frame=prefilter_frame,
                        pixel_delta=pixel_delta,
                    )
                    if prefilter_ratio + prefilter_band < change_threshold:
                        change_ratio = prefilter_ratio
                        keep_image = False
                        skip_via_prefilter = True

                if not skip_via_prefilter:
                    change_ratio = changed_pixel_ratio(
                        previous_frame=previous_kept_frame,
                        current_frame=comparison_frame,
                        pixel_delta=pixel_delta,
                    )
                    keep_image = change_ratio >= change_threshold

            if keep_image:
                destination = output_path_for(image_path, input_dir, filtered_dir)
                shutil.copy2(image_path, destination)
                kept_paths.append(destination)
                previous_kept_frame = comparison_frame
                previous_prefilter_frame = prefilter_frame
                stats.kept += 1
                if change_ratio is None:
                    log_step(
                        "difference-filter",
                        f"[{index}/{total_images}] Kept first frame: "
                        f"{describe_path(image_path, input_dir)} -> "
                        f"{describe_path(destination, filtered_dir)}",
                    )
                else:
                    log_step(
                        "difference-filter",
                        f"[{index}/{total_images}] Kept frame "
                        f"({format_ratio(change_ratio)} change): "
                        f"{describe_path(image_path, input_dir)} -> "
                        f"{describe_path(destination, filtered_dir)}",
                    )
            else:
                stats.skipped_similar += 1
                log_step(
                    "difference-filter",
                    f"[{index}/{total_images}] Skipped similar frame "
                    f"({format_ratio(change_ratio)} change): "
                    f"{describe_path(image_path, input_dir)}",
                )
    finally:
        if worker_count > 1:
            executor.shutdown()

    return kept_paths, stats


def create_video(image_paths: list[Path], output_video: Path, fps: int) -> None:
    if not image_paths:
        raise SystemExit("No images were kept, so no video could be created.")

    Image, _, ImageOps = require_pillow()
    imageio, np = require_video_dependencies()

    output_video.parent.mkdir(parents=True, exist_ok=True)
    target_size = None
    total_frames = len(image_paths)

    log_step(
        "video",
        f"Creating video from {total_frames} frames at {fps} fps: {output_video}",
    )

    with imageio.get_writer(str(output_video), fps=fps, macro_block_size=None) as writer:
        for index, image_path in enumerate(image_paths, start=1):
            with Image.open(image_path) as image:
                frame = ImageOps.exif_transpose(image).convert("RGB")
                if target_size is None:
                    target_size = frame.size
                    resize_note = ""
                elif frame.size != target_size:
                    frame = ImageOps.pad(frame, target_size, color=(0, 0, 0))
                    resize_note = " (padded to match output size)"
                else:
                    resize_note = ""

                writer.append_data(np.asarray(frame))
                log_step(
                    "video",
                    f"[{index}/{total_frames}] Added frame{resize_note}: {image_path}",
                )


def build_video_from_directory(
    input_dir: Path,
    output_video: Path,
    fps: int,
    max_images: int,
) -> int:
    image_paths = iter_image_paths(input_dir, max_images=max_images)
    total_images = len(image_paths)
    log_step(
        "combine-video",
        f"Found {total_images} images in {input_dir}. Combining them into {output_video}.",
    )
    create_video(image_paths, output_video, fps)
    print(f"Frames combined: {total_images}")
    print(f"Video: {output_video}")
    return 0


def print_extraction_summary(stats: ExtractionStats, output_dir: Path) -> None:
    print(f"Scanned: {stats.scanned}")
    print(f"Copied colour images: {stats.copied}")
    print(f"Skipped grayscale images: {stats.skipped_grayscale}")
    print(f"Failed: {stats.failed}")
    print(f"Output folder: {output_dir}")


def print_filter_summary(stats: FilterStats, filtered_dir: Path) -> None:
    print(f"Scanned: {stats.scanned}")
    print(f"Kept after change filter: {stats.kept}")
    print(f"Skipped as too similar: {stats.skipped_similar}")
    print(f"Failed: {stats.failed}")
    print(f"Filtered folder: {filtered_dir}")
