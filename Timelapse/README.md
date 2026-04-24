# Backyard Timelapse Tools

Small Python scripts for processing backyard renovation images into a timelapse.

## What It Does

- `colour_filter.py`: copies only colour images to a new directory
- `difference_filter.py`: copies only meaningfully changed images to a new directory; final keep/skip decisions are processed sequentially so each frame is compared against the last kept frame
- `combine_video.py`: builds a video from a directory of images

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Quick Start

Run each step on its own:

```bash
python3 colour_filter.py <input> <output>
python3 difference_filter.py <input> <output>
python3 combine_video.py <input> <output>
```

## Parameters

### `colour_filter.py`

Required parameters:

- `input_dir`
- `output_dir`

Optional parameters:

- `--sample-size`: `512`
- `--channel-delta`: `10`
- `--colour-pixel-ratio-percent`: `0.5`
- `--max-images`: `0` (`0` means no limit)
- `--sort-by`: `filename` (`filename`, `date-taken`, or `date-modified`)
- `--workers`: `1`

### `difference_filter.py`

Required parameters:

- `input_dir`
- `output_dir`

Optional parameters:

- `--comparison-size`: `320`
- `--pixel-delta`: `12`
- `--change-threshold-percent`: `5.0`
- `--max-images`: `0` (`0` means no limit)
- `--sort-by`: `filename` (`filename`, `date-taken`, or `date-modified`)
- `--prefilter-size`: `64` (`0` disables the fast prefilter)
- `--prefilter-band-percent`: `1.0`
- `--workers`: `1`

### `combine_video.py`

Required parameters:

- `input_dir`
- `output`

Optional parameters:

- `--fps`: `12`
- `--max-images`: `0` (`0` means no limit)
- `--sort-by`: `filename` (`filename`, `date-taken`, or `date-modified`)

## Notes

- By default the scripts process all images
- By default, images are sorted by filename; use `--sort-by date-taken` or `--sort-by date-modified` to change the ordering
- Sorting is applied across the full set of loaded images, not separately within each subfolder
- `date-taken` uses EXIF capture time when available and falls back to file modified time
- Use `--max-images` to limit a run for testing, for example `--max-images 100`

