# ffmpeg-util

Small, scriptable command-line helpers around [`ffmpeg`](https://ffmpeg.org/) for
the media chores you reach for constantly: convert, trim, concatenate,
thumbnail, compress/resize, and probe.

> 📖 Full usage guide: **[MANUAL.md](MANUAL.md)** (CLI, library, desktop UI, packaging).
>
> 🌐 Live showcase: this project on the
> **[JM portfolio](https://jm-portfolio-5afqr6ijoq-uc.a.run.app/#/project/ffmpeg-util)**
> (demo, changelog, releases) · built autonomously by the
> **[Burn Fleet](https://jm-portfolio-5afqr6ijoq-uc.a.run.app/#/monitor)**.

- **Zero runtime dependencies** — pure Python 3.11+ stdlib, shells out to `ffmpeg`/`ffprobe`.
- **`--dry-run` everywhere** — print the exact command before running it.
- **Library + CLI** — import `ffmpeg_util` or use the `ffmpeg-util` command.

## Requirements

`ffmpeg` and `ffprobe` must be installed and on your `PATH`. Override with
`--ffmpeg` / `--ffprobe`, or the `FFMPEG_BIN` / `FFPROBE_BIN` environment variables.

## Install

```bash
pip install -e .          # from a clone
pip install -e ".[dev]"   # with pytest for development
```

## Usage

```bash
# Inspect a file
ffmpeg-util probe input.mkv
ffmpeg-util probe input.mkv --json

# Convert container (stream-copy, fast) or transcode
ffmpeg-util convert input.mkv output.mp4
ffmpeg-util convert input.mkv output.mp4 --vcodec libx265 --acodec aac -y

# Extract audio
ffmpeg-util convert input.mp4 output.mp3 --extract-audio --acodec libmp3lame

# Trim (stream-copy by default; --reencode for frame accuracy)
ffmpeg-util trim input.mp4 clip.mp4 --start 00:01:00 --duration 30
ffmpeg-util trim input.mp4 clip.mp4 --start 60 --end 120 --reencode

# Concatenate files with identical codecs/params
ffmpeg-util concat part1.mp4 part2.mp4 part3.mp4 -o full.mp4
# Note: concatenating stream-copy trims can inflate duration (keyframe alignment).
# Trim with --reencode first if you need exact, gap-free joins.

# Thumbnails
ffmpeg-util thumbnail input.mp4 thumb.png --time 00:00:05 --width 320
ffmpeg-util thumbnail input.mp4 thumbs%d.png --count 6

# Compress / resize (CRF quality or target bitrate)
ffmpeg-util compress input.mp4 small.mp4 --crf 28 --width 1280
ffmpeg-util compress input.mp4 small.mp4 --bitrate 2M
```

Add `--dry-run` to any command to see the generated `ffmpeg` invocation without
running it, and `-v/--verbose` to echo the command and raise ffmpeg's log level.

## Development

The project pins its interpreter via `.python-version` (3.11.9). With
[pyenv](https://github.com/pyenv/pyenv) / [pyenv-win](https://github.com/pyenv-win/pyenv-win):

```bash
pyenv install 3.11.9      # once
pip install -e ".[dev]"
pytest
```

Tests cover binary discovery and command-string construction and run **without**
ffmpeg installed (every command is exercised via `--dry-run`).

## License

MIT
