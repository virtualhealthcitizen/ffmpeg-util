# ffmpeg-util — User Manual

A small, scriptable toolkit around [`ffmpeg`](https://ffmpeg.org/) with two front
ends sharing one core:

- a **CLI** / Python library (`ffmpeg_util`), zero runtime dependencies; and
- an **Electron desktop UI** (`ui/`) backed by a local Python sidecar.

Both cover the same operations: **probe, convert, trim, concat, thumbnail,
contact-sheet, compress (incl. target-size), gif, speed, transform, crop, mute, pad, loop, frames, reverse, volume, fade, grayscale, invert, loudnorm, boomerang, eq, fps, crop-aspect, mono, title, waveform, sample-rate, hstack, vstack, blur-pad, image-to-video, replace-audio**.

---

## 1. Requirements

- `ffmpeg` and `ffprobe` on your `PATH` (or pointed to via flags/env — see §3).
- For the CLI: Python 3.11+.
- For the UI from source: Node.js + the sidecar's Python deps (see §6).

Check ffmpeg is available:

```bash
ffmpeg -version
```

---

## 2. Install (CLI / library)

```bash
pip install -e .            # from a clone
pip install -e ".[dev]"     # with pytest for development
```

This installs the `ffmpeg-util` command. You can also run it as a module:
`python -m ffmpeg_util …`.

---

## 3. Global options (CLI)

These apply to every subcommand:

| Flag | Meaning |
|------|---------|
| `--ffmpeg PATH` / `--ffprobe PATH` | Use a specific binary (else `PATH`, then `FFMPEG_BIN`/`FFPROBE_BIN`). |
| `-y, --overwrite` | Overwrite the output if it exists (default: refuse). |
| `-v, --verbose` | Echo the command and raise ffmpeg's log level. |
| `--dry-run` | Print the ffmpeg command instead of running it. |

`--dry-run` is the fastest way to see exactly what would run:

```bash
ffmpeg-util convert in.mkv out.mp4 --dry-run
```

---

## 4. Commands

### probe — inspect a file
```bash
ffmpeg-util probe input.mkv          # short summary
ffmpeg-util probe input.mkv --json   # raw ffprobe JSON
```

### convert — container / codec / extract audio
Stream-copies by default (fast, no re-encode):
```bash
ffmpeg-util convert in.mkv out.mp4
ffmpeg-util convert in.mkv out.mp4 --vcodec libx265 --acodec aac -y
ffmpeg-util convert in.mp4 out.mp3 --extract-audio --acodec libmp3lame
```

### trim — cut a clip
Stream-copy is keyframe-aligned (fast); `--reencode` is frame-accurate.
Use `--end` **or** `--duration`, not both.
```bash
ffmpeg-util trim in.mp4 clip.mp4 --start 00:01:00 --duration 30
ffmpeg-util trim in.mp4 clip.mp4 --start 60 --end 120 --reencode
```

### concat — join files with identical codecs/params
```bash
ffmpeg-util concat part1.mp4 part2.mp4 part3.mp4 -o full.mp4
```
> Concatenating *stream-copy* trims can inflate duration (keyframe alignment).
> Trim with `--reencode` first if you need exact, gap-free joins.

### thumbnail — a frame, or several
```bash
ffmpeg-util thumbnail in.mp4 thumb.png --time 00:00:05 --width 320
ffmpeg-util thumbnail in.mp4 thumbs%d.png --count 6     # %d for multiple
```

### contact-sheet — tiled montage
```bash
ffmpeg-util contact-sheet in.mp4 sheet.png --cols 4 --rows 4 --width 320
```
Samples `cols*rows` frames evenly; the montage is `cols*width` wide.

### compress — quality, bitrate, or target size
CRF (quality), bitrate, **or** target-size — pick one:
```bash
ffmpeg-util compress in.mp4 small.mp4 --crf 28 --width 1280
ffmpeg-util compress in.mp4 small.mp4 --bitrate 2M
ffmpeg-util compress in.mp4 small.mp4 --target-size 8      # ~8 MB, two-pass
```

### gif — animated GIF (quality two-pass palette)
```bash
ffmpeg-util gif in.mp4 out.gif --fps 12 --width 480 --start 5 --duration 3
```

### speed — faster / slower
`>1` speeds up, `<1` slows down; audio is retimed to match.
```bash
ffmpeg-util speed in.mp4 fast.mp4 --factor 2      # 2x
ffmpeg-util speed in.mp4 slow.mp4 --factor 0.5    # half speed
```

### transform — rotate / flip
`--op` is one of `rotate-cw`, `rotate-ccw`, `rotate-180`, `hflip`, `vflip`.
90° rotations swap width and height.
```bash
ffmpeg-util transform in.mp4 rotated.mp4 --op rotate-cw
ffmpeg-util transform in.mp4 mirrored.mp4 --op hflip
```

### crop — cut out a rectangle
Crops a `--width`×`--height` region with its top-left at (`--x`, `--y`).
```bash
ffmpeg-util crop in.mp4 out.mp4 --width 1280 --height 720 --x 0 --y 140
```

### title — set the metadata title
Sets (or clears, with empty) the title tag; streams are copied.
```bash
ffmpeg-util title in.mp4 out.mp4 --title "My Video"
```

### sample-rate — resample audio
Sets the audio sample rate (Hz); the video is stream-copied.
```bash
ffmpeg-util sample-rate in.mp4 out.mp4 --rate 44100
```

### mono — downmix audio to one channel
Collapses the audio to mono; the video is stream-copied.
```bash
ffmpeg-util mono in.mp4 out.mp4
```

### mute — strip the audio track
Keeps the video (stream-copied, no re-encode); drops audio.
```bash
ffmpeg-util mute in.mp4 silent.mp4
```

### replace-audio — swap in a new audio track
Replaces the video's audio with an external audio file (e.g. a music bed or
voiceover). The video is stream-copied; the new audio is re-encoded to AAC and
the result is trimmed to whichever of the two is shorter.
```bash
ffmpeg-util replace-audio in.mp4 out.mp4 --audio music.mp3
```

### blur-pad — fit into a frame over a blurred fill
Like `pad`, but fills the bars with a blurred, zoomed copy of the video instead of black.
```bash
ffmpeg-util blur-pad in.mp4 out.mp4 --width 1080 --height 1920 --sigma 20
```

### image-to-video — make a video from a still image
Loops a single image into a `--seconds`-long clip at `--fps` (default 30). Useful for
slideshows or pairing a static picture with an audio track.
```bash
ffmpeg-util image-to-video photo.png clip.mp4 --seconds 5 --fps 30
```

### pad — letterbox into a target frame
Scales to fit `--width`×`--height` (keeping aspect), then centers it with black bars.
```bash
ffmpeg-util pad in.mp4 wide.mp4 --width 1920 --height 1080
```

### loop — repeat a clip
Plays the input `--count` times total (stream-copied, no re-encode).
```bash
ffmpeg-util loop in.mp4 looped.mp4 --count 3
```

### frames — extract an image sequence
Writes frames as images, keeping every `--every`th frame. The output must contain
a printf token (e.g. `%04d`).
```bash
ffmpeg-util frames in.mp4 frames/f_%04d.png --every 30
```

### reverse — play a clip backwards
Reverses video and audio. Buffers the whole clip in memory — best for short clips.
```bash
ffmpeg-util reverse in.mp4 backwards.mp4
```

### hstack — side by side
Places two equal-height videos side by side (output width = sum); keeps the left audio.
```bash
ffmpeg-util hstack left.mp4 right.mp4 -o sidebyside.mp4
```

### vstack — stacked
Stacks two equal-width videos vertically (output height = sum); keeps the top audio.
```bash
ffmpeg-util vstack top.mp4 bottom.mp4 -o stacked.mp4
```

### boomerang — forward then reversed
Plays the clip forward then backward (video only), so it runs ~twice as long.
```bash
ffmpeg-util boomerang in.mp4 boomerang.mp4
```

### waveform — render the audio waveform to an image
```bash
ffmpeg-util waveform in.mp4 wave.png --width 1000 --height 200
```

### crop-aspect — center-crop to an aspect ratio
Crops the largest centered region matching `--aspect` (e.g. 16:9, 9:16, 1:1).
```bash
ffmpeg-util crop-aspect in.mp4 wide.mp4 --aspect 16:9
```

### fps — change frame rate (same speed)
Resamples to `--fps` frames/sec without changing duration (unlike `speed`).
```bash
ffmpeg-util fps in.mp4 out.mp4 --fps 30
```

### eq — adjust brightness / contrast / saturation
Defaults are no-ops (`--brightness 0`, `--contrast 1`, `--saturation 1`).
```bash
ffmpeg-util eq in.mp4 out.mp4 --brightness 0.1 --contrast 1.2 --saturation 1.3
```

### grayscale — desaturate to black & white
```bash
ffmpeg-util grayscale in.mp4 bw.mp4
```

### invert — invert colors (photo-negative)
Inverts every color to its opposite (the `negate` filter); audio is untouched.
```bash
ffmpeg-util invert in.mp4 negative.mp4
```

### fade — fade in/out (black)
Fades video and audio in from black at the start and out to black at the end;
`--duration` is the fade length applied to each end.
```bash
ffmpeg-util fade in.mp4 out.mp4 --duration 1.5
```

### volume — adjust loudness
Applies a dB `--gain` to audio (video copied). Use `--gain=-6` for negatives.
```bash
ffmpeg-util volume in.mp4 louder.mp4 --gain 3
ffmpeg-util volume in.mp4 quieter.mp4 --gain=-6
```

### loudnorm — normalize loudness (EBU R128)
Normalizes integrated loudness to a `--target` (LUFS). Common targets: -16 (web),
-14 (streaming), -23 (broadcast).
```bash
ffmpeg-util loudnorm in.mp4 normalized.mp4 --target -14
```

---

## 5. Using as a library

```python
from ffmpeg_util.runner import FfmpegRunner
from ffmpeg_util import commands

runner = FfmpegRunner(overwrite=True)
print(commands.probe(runner, "in.mp4"))
runner.run_ffmpeg(commands.build_convert_args("in.mkv", "out.mp4"))
commands.make_gif(runner, "in.mp4", "out.gif", fps=12, width=480)
```

`FfmpegRunner(dry_run=True)` prints commands instead of executing — handy for
tests. `runner.iter_ffmpeg_progress(args)` yields ffmpeg `-progress` blocks for
live progress.

---

## 6. The desktop UI

The UI mirrors the commands as tabs (Convert, Trim, Concat, Thumbnail, Compress,
GIF, Speed, Transform, Crop, Mute, Pad, Loop, Frames, Reverse, Volume, Fade, Grayscale, Invert, Loudness, Boomerang, Adjust, FPS, Aspect, Mono, Title, Waveform, Sample rate, Side by side, Stacked, Blur pad, Image → video, Replace audio), with: a **Probe** button per input, **drag-and-drop** (drop a file to
load it into the active tab), a **live progress bar**, an **inline preview** of
image and video outputs, and **persisted** option fields across launches.

Run from source:
```bash
cd ui
npm install
pip install -r sidecar/requirements.txt
npm start
```

The app auto-discovers a working Python for the sidecar; override with
`FFMPEG_UTIL_PYTHON` if needed. See [ui/README.md](ui/README.md) for the
architecture and packaging (`npm run pack` builds a standalone app with a
bundled, Python-free sidecar).

---

## 7. Testing

```bash
pytest                       # core library + CLI
pytest ui/sidecar/tests      # sidecar integration (real ffmpeg; skips if absent)
cd ui && npm test            # renderer logic (node:test)
```

---

## 8. Troubleshooting

- **"Could not find 'ffmpeg'"** — install ffmpeg and ensure it's on `PATH`, or pass
  `--ffmpeg` / set `FFMPEG_BIN`.
- **Output refuses to overwrite** — add `-y` / `--overwrite`.
- **`trim`/`concat` durations look off** — that's stream-copy keyframe alignment;
  re-encode for exact cuts (`trim --reencode`).
- **UI sidecar won't start** — ensure the sidecar's Python deps are installed, or
  set `FFMPEG_UTIL_PYTHON` to a Python that has them.
