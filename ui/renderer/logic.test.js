// Unit tests for the pure renderer logic. Run with: node --test
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./logic");

test("isImagePath detects image extensions (case-insensitive)", () => {
  assert.equal(L.isImagePath("a.png"), true);
  assert.equal(L.isImagePath("A.JPG"), true);
  assert.equal(L.isImagePath("frame.webp"), true);
  assert.equal(L.isImagePath("clip.mp4"), false);
  assert.equal(L.isImagePath("noext"), false);
});

test("isVideoPath detects video extensions", () => {
  assert.equal(L.isVideoPath("a.mp4"), true);
  assert.equal(L.isVideoPath("B.MKV"), true);
  assert.equal(L.isVideoPath("a.png"), false);
});

test("previewKind classifies image, video, or none", () => {
  assert.deepEqual(L.previewKind("thumbs%d.png"), { kind: "image", path: "thumbs1.png" });
  assert.deepEqual(L.previewKind("out.mp4"), { kind: "video", path: "out.mp4" });
  assert.deepEqual(L.previewKind("audio.mp3"), { kind: null, path: "audio.mp3" });
});

test("suggestOutput swaps the extension", () => {
  assert.equal(L.suggestOutput("C:\\v\\in.mkv"), "C:\\v\\in.out.mp4");
  assert.equal(L.suggestOutput("in.mov", ".small.mp4"), "in.small.mp4");
  assert.equal(L.suggestOutput("", ".out.mp4"), "output.out.mp4");
  assert.equal(L.suggestOutput(""), "output.out.mp4");
});

test("previewPath replaces %d with 1", () => {
  assert.equal(L.previewPath("thumbs%d.png"), "thumbs1.png");
  assert.equal(L.previewPath("a%d-b%d.png"), "a1-b1.png");
  assert.equal(L.previewPath("thumb.png"), "thumb.png");
});

test("parseLines trims and drops blanks", () => {
  assert.deepEqual(L.parseLines("a.mp4\n  b.mp4 \n\n c.mp4 \n"), [
    "a.mp4", "b.mp4", "c.mp4",
  ]);
  assert.deepEqual(L.parseLines(""), []);
  assert.deepEqual(L.parseLines("   \n  "), []);
});

test("fieldLabel strips the op prefix", () => {
  assert.equal(L.fieldLabel("compress-crf"), "crf");
  assert.equal(L.fieldLabel("trim-input"), "input");
});

test("parseSseBuffer parses complete events and keeps the remainder", () => {
  const buf =
    'data: {"type":"progress","percent":10}\n\n' +
    'data: {"type":"progress","percent":50}\n\n' +
    'data: {"type":"done","output":"o.mp4"';
  const { events, remainder } = L.parseSseBuffer(buf);
  assert.equal(events.length, 2);
  assert.equal(events[0].percent, 10);
  assert.equal(events[1].percent, 50);
  assert.equal(remainder, 'data: {"type":"done","output":"o.mp4"');
});

test("parseSseBuffer ignores malformed blocks", () => {
  const { events } = L.parseSseBuffer('data: not-json\n\ndata: {"type":"done"}\n\n');
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "done");
});

test("inputTargetForTab maps tabs to fields", () => {
  assert.deepEqual(L.inputTargetForTab("convert"), { id: "convert-input", append: false });
  assert.deepEqual(L.inputTargetForTab("compress"), { id: "compress-input", append: false });
  assert.deepEqual(L.inputTargetForTab("concat"), { id: "concat-inputs", append: true });
  // every other single-input tab is supported generically (not just a hardcoded few)
  assert.deepEqual(L.inputTargetForTab("eq"), { id: "eq-input", append: false });
  assert.deepEqual(L.inputTargetForTab("blur_pad"), { id: "blur_pad-input", append: false });
  // the two-input stack tabs drop into the first slot
  assert.deepEqual(L.inputTargetForTab("hstack"), { id: "hstack-input-a", append: false });
  assert.deepEqual(L.inputTargetForTab("vstack"), { id: "vstack-input-a", append: false });
  assert.equal(L.inputTargetForTab(""), null);
});

test("dropUpdate sets a single input for non-concat tabs", () => {
  assert.deepEqual(L.dropUpdate(["a.mp4", "b.mp4"], "convert"), {
    id: "convert-input",
    value: "a.mp4", // first file only
  });
});

test("dropUpdate appends to existing concat list", () => {
  assert.deepEqual(L.dropUpdate(["b.mp4", "c.mp4"], "concat", "a.mp4\n"), {
    id: "concat-inputs",
    value: "a.mp4\nb.mp4\nc.mp4",
  });
  assert.deepEqual(L.dropUpdate(["x.mp4"], "concat", ""), {
    id: "concat-inputs",
    value: "x.mp4",
  });
});

test("dropUpdate returns null for empty paths or no tab", () => {
  assert.equal(L.dropUpdate([], "convert"), null);
  assert.equal(L.dropUpdate(["a.mp4"], ""), null);
});

test("dropUpdate works for a generic single-input tab", () => {
  assert.deepEqual(L.dropUpdate(["a.mp4"], "eq"), { id: "eq-input", value: "a.mp4" });
});

test("filterTools returns every tab for an empty/whitespace query", () => {
  const tools = [
    { tab: "convert", label: "Convert", keywords: "" },
    { tab: "trim", label: "Trim", keywords: "cut" },
  ];
  assert.deepEqual(L.filterTools("", tools), ["convert", "trim"]);
  assert.deepEqual(L.filterTools("   ", tools), ["convert", "trim"]);
  assert.deepEqual(L.filterTools(null, tools), ["convert", "trim"]);
});

test("filterTools matches on label (case-insensitive) and preserves order", () => {
  const tools = [
    { tab: "convert", label: "Convert", keywords: "" },
    { tab: "compress", label: "Compress", keywords: "" },
    { tab: "trim", label: "Trim", keywords: "" },
  ];
  assert.deepEqual(L.filterTools("co", tools), ["convert", "compress"]);
  assert.deepEqual(L.filterTools("TRIM", tools), ["trim"]);
});

test("filterTools matches on alias keywords, not just the label", () => {
  const tools = [
    { tab: "transform", label: "Transform", keywords: "rotate flip mirror" },
    { tab: "compress", label: "Compress", keywords: "resize scale shrink" },
  ];
  assert.deepEqual(L.filterTools("rotate", tools), ["transform"]);
  assert.deepEqual(L.filterTools("resize", tools), ["compress"]);
});

test("filterTools AND-matches every whitespace token", () => {
  const tools = [
    { tab: "transform", label: "Transform", keywords: "rotate flip mirror turn" },
    { tab: "crop", label: "Crop", keywords: "rectangle edges" },
  ];
  assert.deepEqual(L.filterTools("rotate flip", tools), ["transform"]);
  assert.deepEqual(L.filterTools("rotate edges", tools), []); // no single tool has both
});

test("filterTools returns [] when nothing matches", () => {
  const tools = [{ tab: "convert", label: "Convert", keywords: "" }];
  assert.deepEqual(L.filterTools("zzz", tools), []);
});

test("TOOL_ALIASES covers tabs and is searchable via filterTools", () => {
  // Build the same tool list the renderer builds, from the alias table.
  const tools = Object.keys(L.TOOL_ALIASES).map((tab) => ({
    tab,
    label: tab,
    keywords: L.TOOL_ALIASES[tab],
  }));
  assert.ok(tools.length >= 28); // ~30 tools
  assert.deepEqual(L.filterTools("letterbox", tools).sort(), ["blur_pad", "pad"]);
  assert.deepEqual(L.filterTools("lufs", tools), ["loudnorm"]);
  assert.deepEqual(L.filterTools("backwards", tools), ["reverse"]);
});

test("formatBytes scales to KB/MB/GB", () => {
  assert.equal(L.formatBytes(0), "0 B");
  assert.equal(L.formatBytes(512), "512 B");
  assert.equal(L.formatBytes(1536), "1.5 KB");
  assert.equal(L.formatBytes(5 * 1024 * 1024), "5.0 MB");
  assert.equal(L.formatBytes(1024 * 1024 * 1024), "1.0 GB");
  assert.equal(L.formatBytes("2048"), "2.0 KB"); // numeric strings (ffprobe)
  assert.equal(L.formatBytes("nope"), null);
});

test("formatDuration renders M:SS and H:MM:SS", () => {
  assert.equal(L.formatDuration(5), "0:05");
  assert.equal(L.formatDuration(65), "1:05");
  assert.equal(L.formatDuration(3661), "1:01:01");
  assert.equal(L.formatDuration("12.5"), "0:13");
  assert.equal(L.formatDuration(null), null);
});

test("parseFrameRate handles ratios and plain numbers", () => {
  assert.equal(L.parseFrameRate("30/1"), 30);
  assert.equal(Math.round(L.parseFrameRate("30000/1001") * 100) / 100, 29.97);
  assert.equal(L.parseFrameRate("25"), 25);
  assert.equal(L.parseFrameRate("0/0"), null);
  assert.equal(L.parseFrameRate(null), null);
});

test("channelLabel names mono/stereo/N ch", () => {
  assert.equal(L.channelLabel(1), "mono");
  assert.equal(L.channelLabel(2), "stereo");
  assert.equal(L.channelLabel(6), "6 ch");
  assert.equal(L.channelLabel(0), null);
});

test("summarizeProbe builds ordered chips from ffprobe JSON", () => {
  const data = {
    format: { duration: "65", size: "5242880" },
    streams: [
      { codec_type: "video", codec_name: "h264", width: 1920, height: 1080, avg_frame_rate: "30/1" },
      { codec_type: "audio", codec_name: "aac", channels: 2, sample_rate: "48000" },
    ],
  };
  assert.deepEqual(L.summarizeProbe(data), [
    { label: "Duration", value: "1:05" },
    { label: "Size", value: "1920×1080" },
    { label: "FPS", value: "30 fps" },
    { label: "Video", value: "h264" },
    { label: "Audio", value: "aac" },
    { label: "Channels", value: "stereo" },
    { label: "Rate", value: "48 kHz" },
    { label: "File", value: "5.0 MB" },
  ]);
});

test("summarizeProbe skips missing facts (audio-only, no size)", () => {
  const data = {
    format: { duration: "12" },
    streams: [{ codec_type: "audio", codec_name: "mp3", channels: 1, sample_rate: "44100" }],
  };
  assert.deepEqual(L.summarizeProbe(data), [
    { label: "Duration", value: "0:12" },
    { label: "Audio", value: "mp3" },
    { label: "Channels", value: "mono" },
    { label: "Rate", value: "44.1 kHz" },
  ]);
});

test("summarizeProbe tolerates empty/garbage input", () => {
  assert.deepEqual(L.summarizeProbe(null), []);
  assert.deepEqual(L.summarizeProbe({}), []);
  assert.deepEqual(L.summarizeProbe({ streams: "nope" }), []);
});

test("sourceFillActions maps the Size chip to a tab's width/height fields", () => {
  const data = { streams: [{ codec_type: "video", width: 1920, height: 1080, avg_frame_rate: "30/1" }] };
  assert.deepEqual(L.sourceFillActions("blur_pad", data), {
    Size: [
      { id: "blur_pad-width", value: "1920" },
      { id: "blur_pad-height", value: "1080" },
    ],
  });
  assert.deepEqual(L.sourceFillActions("compress", data), {
    Size: [
      { id: "compress-width", value: "1920" },
      { id: "compress-height", value: "1080" },
    ],
  });
});

test("sourceFillActions handles width-only tabs and the FPS tab", () => {
  const data = { streams: [{ codec_type: "video", width: 640, height: 360, r_frame_rate: "25/1" }] };
  assert.deepEqual(L.sourceFillActions("gif", data), { Size: [{ id: "gif-width", value: "640" }] });
  assert.deepEqual(L.sourceFillActions("fps", data), { FPS: [{ id: "fps-fps", value: "25" }] });
});

test("sourceFillActions returns {} when the tab has no fillable fields or no video", () => {
  const video = { streams: [{ codec_type: "video", width: 100, height: 50, avg_frame_rate: "30/1" }] };
  assert.deepEqual(L.sourceFillActions("convert", video), {}); // no dimension/fps fields
  const audioOnly = { streams: [{ codec_type: "audio", channels: 2 }] };
  assert.deepEqual(L.sourceFillActions("crop", audioOnly), {}); // no video dims
  assert.deepEqual(L.sourceFillActions("crop", null), {});
});

test("dimensionPresetTabs covers both-width-and-height tabs only", () => {
  const tabs = L.dimensionPresetTabs();
  for (const t of ["crop", "pad", "blur_pad", "compress", "waveform"]) {
    assert.ok(tabs.includes(t), `expected ${t} in dimension preset tabs`);
  }
  // width-only tabs have no height field, so they're excluded
  assert.equal(tabs.includes("gif"), false);
  assert.equal(tabs.includes("thumbnail"), false);
});

test("presetDimensions returns fixed resolutions verbatim", () => {
  const p720 = L.DIMENSION_PRESETS.find((p) => p.key === "720p");
  assert.deepEqual(L.presetDimensions(p720, {}), { width: 1280, height: 720 });
  const p4k = L.DIMENSION_PRESETS.find((p) => p.key === "2160p");
  assert.deepEqual(L.presetDimensions(p4k, { width: 100 }), { width: 3840, height: 2160 });
});

test("presetDimensions derives height from the current width for ratio presets", () => {
  const wide = { ratio: [16, 9] };
  assert.deepEqual(L.presetDimensions(wide, { width: 1920 }), { width: 1920, height: 1080 });
  const tall = { ratio: [9, 16] };
  assert.deepEqual(L.presetDimensions(tall, { width: 1080 }), { width: 1080, height: 1920 });
  const square = { ratio: [1, 1] };
  assert.deepEqual(L.presetDimensions(square, { width: 500 }), { width: 500, height: 500 });
});

test("presetDimensions falls back to source width, then 1280, and rounds even", () => {
  const wide = { ratio: [16, 9] };
  assert.deepEqual(L.presetDimensions(wide, { sourceWidth: 640 }), { width: 640, height: 360 });
  assert.deepEqual(L.presetDimensions(wide, {}), { width: 1280, height: 720 });
  // odd base width is bumped to even, and the derived height too
  assert.deepEqual(L.presetDimensions(wide, { width: 853 }), { width: 854, height: 480 });
});

test("presetDimensions matches source dims only when probed", () => {
  const match = { match: true };
  assert.deepEqual(L.presetDimensions(match, { sourceWidth: 320, sourceHeight: 240 }), { width: 320, height: 240 });
  assert.equal(L.presetDimensions(match, {}), null);
  assert.equal(L.presetDimensions(null, {}), null);
});

test("videoDims pulls first video stream size, else null", () => {
  assert.deepEqual(
    L.videoDims({ streams: [{ codec_type: "audio" }, { codec_type: "video", width: 1920, height: 1080 }] }),
    { w: 1920, h: 1080 }
  );
  assert.equal(L.videoDims({ streams: [{ codec_type: "audio", channels: 2 }] }), null);
  assert.equal(L.videoDims({ streams: [{ codec_type: "video", width: 0, height: 0 }] }), null);
  assert.equal(L.videoDims(null), null);
});

test("compatReport flags hstack height mismatch / vstack width mismatch", () => {
  const a = { w: 320, h: 240 }, tallerSameW = { w: 320, h: 360 }, widerSameH = { w: 480, h: 240 };
  // hstack needs equal heights
  assert.equal(L.compatReport("hstack", [a, tallerSameW]).ok, false);
  assert.match(L.compatReport("hstack", [a, tallerSameW]).message, /Heights differ \(240 vs 360/);
  assert.equal(L.compatReport("hstack", [a, widerSameH]).ok, true); // heights both 240
  // vstack needs equal widths
  assert.equal(L.compatReport("vstack", [a, widerSameH]).ok, false);
  assert.match(L.compatReport("vstack", [a, widerSameH]).message, /Widths differ \(320 vs 480/);
  assert.equal(L.compatReport("vstack", [a, tallerSameW]).ok, true); // widths both 320
});

test("compatReport checks concat size match", () => {
  const a = { w: 320, h: 240 };
  assert.equal(L.compatReport("concat", [a, a, a]).ok, true);
  assert.match(L.compatReport("concat", [a, { w: 640, h: 480 }]).message, /differ in size \(320×240, 640×480\)/);
});

test("compatReport returns null when it doesn't apply", () => {
  assert.equal(L.compatReport("convert", [{ w: 1, h: 1 }, { w: 2, h: 2 }]), null); // not multi-input
  assert.equal(L.compatReport("hstack", [{ w: 320, h: 240 }]), null); // only one input
  assert.equal(L.compatReport("hstack", [{ w: 320, h: 240 }, null]), null); // second not probed yet
});

test("formatTimecode renders HH:MM:SS.mmm with correct ms carry", () => {
  assert.equal(L.formatTimecode(0), "00:00:00.000");
  assert.equal(L.formatTimecode(1.5), "00:00:01.500");
  assert.equal(L.formatTimecode(65.25), "00:01:05.250");
  assert.equal(L.formatTimecode(3661.007), "01:01:01.007");
  assert.equal(L.formatTimecode(1.9999), "00:00:02.000"); // ms rounds up & carries
  assert.equal(L.formatTimecode(-5), "00:00:00.000"); // clamp negatives
});

test("timeTargetsForTab maps trim/gif/thumbnail to their time fields", () => {
  assert.deepEqual(L.timeTargetsForTab("trim"), [
    { id: "trim-start", label: "start" },
    { id: "trim-end", label: "end" },
  ]);
  assert.deepEqual(L.timeTargetsForTab("gif"), [{ id: "gif-start", label: "start" }]);
  assert.deepEqual(L.timeTargetsForTab("thumbnail"), [{ id: "thumbnail-time", label: "time" }]);
  assert.deepEqual(L.timeTargetsForTab("convert"), []);
  assert.deepEqual(L.timeTargetsForTab("compress"), []);
});

test("overwriteMessage names the path and asks to overwrite", () => {
  const msg = L.overwriteMessage("C:\\out\\clip.mp4");
  assert.match(msg, /clip\.mp4/);
  assert.match(msg, /already exists/);
  assert.match(msg, /[Oo]verwrite/);
});

test("isPathFieldId flags input/output path fields, not option fields", () => {
  assert.equal(L.isPathFieldId("compress-input"), true);
  assert.equal(L.isPathFieldId("compress-output"), true);
  assert.equal(L.isPathFieldId("concat-inputs"), true);
  assert.equal(L.isPathFieldId("hstack-input-a"), true);
  assert.equal(L.isPathFieldId("hstack-input-b"), true);
  assert.equal(L.isPathFieldId("compress-crf"), false);
  assert.equal(L.isPathFieldId("gif-fps"), false);
});

test("preset helpers store/list/get/remove per tab immutably", () => {
  let p = {};
  p = L.withPreset(p, "compress", "web", { "compress-crf": "28" });
  p = L.withPreset(p, "compress", "hq", { "compress-crf": "18" });
  p = L.withPreset(p, "gif", "small", { "gif-fps": "10" });
  // sorted names, scoped per tab
  assert.deepEqual(L.presetNames(p, "compress"), ["hq", "web"]);
  assert.deepEqual(L.presetNames(p, "gif"), ["small"]);
  assert.deepEqual(L.presetNames(p, "trim"), []);
  // get returns stored values, or null when absent
  assert.deepEqual(L.getPreset(p, "compress", "web"), { "compress-crf": "28" });
  assert.equal(L.getPreset(p, "compress", "nope"), null);
  // remove is scoped and leaves siblings intact
  const before = JSON.stringify(p);
  const p2 = L.withoutPreset(p, "compress", "web");
  assert.deepEqual(L.presetNames(p2, "compress"), ["hq"]);
  assert.deepEqual(L.presetNames(p2, "gif"), ["small"]);
  assert.equal(JSON.stringify(p), before, "withoutPreset must not mutate input");
});

test("withPreset overwrites a same-named preset", () => {
  let p = L.withPreset({}, "eq", "warm", { "eq-brightness": "0.1" });
  p = L.withPreset(p, "eq", "warm", { "eq-brightness": "0.3" });
  assert.deepEqual(L.getPreset(p, "eq", "warm"), { "eq-brightness": "0.3" });
  assert.deepEqual(L.presetNames(p, "eq"), ["warm"]);
});

test("parseSseBuffer reassembles an event split across chunks", () => {
  // Simulate streaming: first chunk has a partial event, second completes it.
  let buf = 'data: {"type":"prog';
  let r1 = L.parseSseBuffer(buf);
  assert.equal(r1.events.length, 0);
  buf = r1.remainder + 'ress","percent":99}\n\n';
  let r2 = L.parseSseBuffer(buf);
  assert.equal(r2.events.length, 1);
  assert.equal(r2.events[0].percent, 99);
});

test("parseTimeToSeconds parses secs / M:SS / H:MM:SS(.ms)", () => {
  assert.equal(L.parseTimeToSeconds("5"), 5);
  assert.equal(L.parseTimeToSeconds("1:05"), 65);
  assert.equal(L.parseTimeToSeconds("00:00:01.500"), 1.5);
  assert.equal(L.parseTimeToSeconds("1:01:01"), 3661);
  assert.equal(L.parseTimeToSeconds(""), null);
  assert.equal(L.parseTimeToSeconds("nope"), null);
});

test("parseBitrateBps parses k/M/G suffixes (decimal)", () => {
  assert.equal(L.parseBitrateBps("2M"), 2_000_000);
  assert.equal(L.parseBitrateBps("500k"), 500_000);
  assert.equal(L.parseBitrateBps("800000"), 800_000);
  assert.equal(L.parseBitrateBps("2.5M"), 2_500_000);
  assert.equal(L.parseBitrateBps(""), null);
  assert.equal(L.parseBitrateBps("abc"), null);
});

test("estimateOutput predicts duration for length-changing ops", () => {
  assert.equal(L.estimateOutput("speed", 10, { factor: "2" }), "~0:05");
  assert.equal(L.estimateOutput("loop", 10, { count: "3" }), "~0:30");
  assert.equal(L.estimateOutput("boomerang", 10, {}), "~0:20");
  assert.equal(L.estimateOutput("trim", 10, { duration: "4" }), "~0:04");
  assert.equal(L.estimateOutput("trim", 10, { start: "2", end: "8" }), "~0:06");
  assert.equal(L.estimateOutput("trim", 10, { start: "3" }), "~0:07");
});

test("estimateOutput predicts compress size only when target/bitrate given", () => {
  assert.equal(L.estimateOutput("compress", 10, { target: "5" }), "~5.0 MB");
  assert.equal(L.estimateOutput("compress", 10, { bitrate: "2M" }), "~2.4 MB"); // 2e6*10/8 bytes
  assert.equal(L.estimateOutput("compress", 10, { crf: "23" }), null); // CRF not predictable
  assert.equal(L.estimateOutput("compress", 10, {}), null);
});

test("estimateOutput returns null when not applicable / no duration", () => {
  assert.equal(L.estimateOutput("convert", 10, {}), null);
  assert.equal(L.estimateOutput("speed", null, { factor: "2" }), null); // no probed duration
  assert.equal(L.estimateOutput("speed", 10, { factor: "0" }), null); // invalid factor
});

test("friendlyError maps common ffmpeg failures to a hint", () => {
  assert.match(
    L.friendlyError("clip.mp4: No such file or directory"),
    /path doesn't exist/
  );
  assert.match(
    L.friendlyError("[libx264 @ 0x..] height not divisible by 2 (320x241)"),
    /even numbers/
  );
  assert.match(L.friendlyError("Unknown encoder 'libx265zzz'"), /Unrecognized codec/);
  assert.match(
    L.friendlyError("Unable to find a suitable output format for 'out.zzz'"),
    /output file's extension/
  );
  assert.match(L.friendlyError("Permission denied"), /Permission denied/);
  assert.match(L.friendlyError("moov atom not found"), /moov atom/);
  assert.match(
    L.friendlyError("clip.bin: Invalid data found when processing input"),
    /valid media file/
  );
  assert.match(
    L.friendlyError("Stream map '0:a' matches no streams."),
    /required stream is missing/
  );
  assert.match(L.friendlyError("No space left on device"), /disk is full/);
});

test("friendlyError prefers the specific cause over the generic fallback", () => {
  // ffmpeg prints "Conversion failed!" alongside the real cause — the specific
  // rule must win over the generic last-resort one.
  const stderr =
    "[libx264 @ 0x] height not divisible by 2 (101x57)\n" +
    "Error while filtering\nConversion failed!";
  assert.match(L.friendlyError(stderr), /even numbers/);
  // a bare generic failure still gets the soft fallback
  assert.match(L.friendlyError("Conversion failed!"), /couldn't complete/);
});

test("friendlyError returns null for unrecognized / empty text", () => {
  assert.equal(L.friendlyError("some totally novel ffmpeg gripe"), null);
  assert.equal(L.friendlyError(""), null);
  assert.equal(L.friendlyError(null), null);
});

test("suggestOutputForTab adds an op suffix and keeps the input extension", () => {
  assert.equal(L.suggestOutputForTab("C:\\v\\clip.mkv", "compress"), "C:\\v\\clip.small.mkv");
  assert.equal(L.suggestOutputForTab("in.mp4", "trim"), "in.trim.mp4");
  assert.equal(L.suggestOutputForTab("/a/b/movie.mov", "speed"), "/a/b/movie.speed.mov");
});

test("suggestOutputForTab overrides the extension for type-changing ops", () => {
  assert.equal(L.suggestOutputForTab("clip.mp4", "gif"), "clip.anim.gif");
  assert.equal(L.suggestOutputForTab("clip.mp4", "waveform"), "clip.wave.png");
  assert.equal(L.suggestOutputForTab("clip.mp4", "thumbnail"), "clip.thumb.png");
  assert.equal(L.suggestOutputForTab("clip.mp4", "frames"), "clip.frame_%04d.png");
  assert.equal(L.suggestOutputForTab("still.png", "image_to_video"), "still.clip.mp4");
});

test("suggestOutputForTab falls back for unknown tabs and empty input", () => {
  // unknown tab -> tag from the tab name (underscores stripped) + input ext
  assert.equal(L.suggestOutputForTab("a.webm", "brand_new"), "a.brandnew.webm");
  // no extension -> default .mp4
  assert.equal(L.suggestOutputForTab("noext", "trim"), "noext.trim.mp4");
  // no input -> empty string (nothing to suggest)
  assert.equal(L.suggestOutputForTab("", "trim"), "");
  assert.equal(L.suggestOutputForTab(null, "trim"), "");
});

test("applyOutputTemplate substitutes known tokens and leaves unknown ones", () => {
  const ctx = { name: "clip", op: "compress", w: 320, h: 240, date: "2026-06-27" };
  assert.equal(L.applyOutputTemplate("{name}-{op}", ctx), "clip-compress");
  assert.equal(L.applyOutputTemplate("{name}_{w}x{h}", ctx), "clip_320x240");
  assert.equal(L.applyOutputTemplate("{name}.{wxh}", ctx), "clip.320x240");
  assert.equal(L.applyOutputTemplate("{name}-{date}", ctx), "clip-2026-06-27");
  // unknown tokens are kept literally
  assert.equal(L.applyOutputTemplate("{name}-{bogus}", ctx), "clip-{bogus}");
});

test("applyOutputTemplate resolves missing values to empty (wxh needs both)", () => {
  assert.equal(L.applyOutputTemplate("{name}{w}", { name: "c" }), "c");
  assert.equal(L.applyOutputTemplate("a{wxh}b", { name: "c", w: 320 }), "ab");
  assert.equal(L.applyOutputTemplate("a{wxh}b", { w: 320, h: 240 }), "a320x240b");
  assert.equal(L.applyOutputTemplate("", { name: "c" }), "");
});

test("splitPath separates dir and extension-less name for both separators", () => {
  assert.deepEqual(L.splitPath("C:\\v\\clip.mkv"), { dir: "C:\\v\\", name: "clip" });
  assert.deepEqual(L.splitPath("/a/b/movie.mov"), { dir: "/a/b/", name: "movie" });
  assert.deepEqual(L.splitPath("bare.mp4"), { dir: "", name: "bare" });
  assert.deepEqual(L.splitPath("noext"), { dir: "", name: "noext" });
});

test("templatedOutputForTab keeps the dir + op extension and fills tokens", () => {
  const dims = { w: 320, h: 240 }; // videoDims shape
  assert.equal(
    L.templatedOutputForTab("C:\\v\\clip.mkv", "compress", "{name}-{op}-{wxh}", dims, "2026-06-27"),
    "C:\\v\\clip-compress-320x240.mkv"
  );
  // type-changing op overrides the extension (gif), and {width,height} shape works
  assert.equal(
    L.templatedOutputForTab("/a/movie.mp4", "gif", "{name}_{date}", { width: 640, height: 480 }, "2026-06-27"),
    "/a/movie_2026-06-27.gif"
  );
});

test("templatedOutputForTab strips path separators and reserved chars", () => {
  // a slash in the resolved stem must not break out of the input dir
  assert.equal(
    L.templatedOutputForTab("/a/clip.mp4", "trim", "{name}/sub:?", null, "2026-06-27"),
    "/a/clipsub.mp4"
  );
});

test("templatedOutputForTab returns '' to signal fallback when unusable", () => {
  assert.equal(L.templatedOutputForTab("", "trim", "{name}", null, "d"), "");
  assert.equal(L.templatedOutputForTab("a.mp4", "trim", "", null, "d"), "");
  assert.equal(L.templatedOutputForTab("a.mp4", "trim", "   ", null, "d"), "");
  // a template that resolves to nothing usable -> "" (caller falls back)
  assert.equal(L.templatedOutputForTab("a.mp4", "trim", "{w}", null, "d"), "");
});

test("extOf returns the lowercase extension or empty", () => {
  assert.equal(L.extOf("a.MP4"), ".mp4");
  assert.equal(L.extOf("/x/y.tar.gz"), ".gz");
  assert.equal(L.extOf("noext"), "");
  assert.equal(L.extOf("C:\\dir.with.dot\\file"), "");
});

test("normalizeDragRect normalizes points dragged in any direction", () => {
  // top-left -> bottom-right
  assert.deepEqual(L.normalizeDragRect({ x: 10, y: 20 }, { x: 110, y: 80 }), {
    left: 10, top: 20, width: 100, height: 60,
  });
  // bottom-right -> top-left (drag back up) yields the same rect
  assert.deepEqual(L.normalizeDragRect({ x: 110, y: 80 }, { x: 10, y: 20 }), {
    left: 10, top: 20, width: 100, height: 60,
  });
  // a zero-area click
  assert.deepEqual(L.normalizeDragRect({ x: 5, y: 5 }, { x: 5, y: 5 }), {
    left: 5, top: 5, width: 0, height: 0,
  });
});

test("clampPoint clamps to the displayed media box", () => {
  const size = { width: 280, height: 170 };
  assert.deepEqual(L.clampPoint({ x: 100, y: 50 }, size), { x: 100, y: 50 });
  assert.deepEqual(L.clampPoint({ x: -10, y: 200 }, size), { x: 0, y: 170 });
  assert.deepEqual(L.clampPoint({ x: 999, y: -5 }, size), { x: 280, y: 0 });
});

test("rectToCrop scales display px to even source-px crop values", () => {
  // 280×140 display maps a 1280×640 source: scale ×4.571 / ×4.571
  const display = { width: 280, height: 140 };
  const source = { width: 1280, height: 640 };
  // a full-frame drag covers the whole source
  assert.deepEqual(L.rectToCrop({ left: 0, top: 0, width: 280, height: 140 }, display, source), {
    x: 0, y: 0, width: 1280, height: 640,
  });
  // a centered quarter-ish rect scales up and rounds to even
  const c = L.rectToCrop({ left: 70, top: 35, width: 140, height: 70 }, display, source);
  assert.equal(c.x % 2, 0);
  assert.equal(c.width % 2, 0);
  assert.equal(c.x, 320);
  assert.equal(c.y, 160);
  assert.equal(c.width, 640);
  assert.equal(c.height, 320);
});

test("rectToCrop clamps to the source frame and never overflows", () => {
  const display = { width: 200, height: 100 };
  const source = { width: 400, height: 200 };
  // a rect that runs off the right/bottom edge stays in-bounds (x+w ≤ sw)
  const c = L.rectToCrop({ left: 150, top: 80, width: 100, height: 50 }, display, source);
  assert.ok(c.x + c.width <= source.width, `${c.x}+${c.width} ≤ ${source.width}`);
  assert.ok(c.y + c.height <= source.height, `${c.y}+${c.height} ≤ ${source.height}`);
});

test("rectToCrop returns null for degenerate rects or missing sizes", () => {
  const display = { width: 200, height: 100 }, source = { width: 400, height: 200 };
  assert.equal(L.rectToCrop({ left: 0, top: 0, width: 0, height: 50 }, display, source), null);
  assert.equal(L.rectToCrop({ left: 0, top: 0, width: 1, height: 1 }, { width: 0, height: 0 }, source), null);
  assert.equal(L.rectToCrop({ left: 0, top: 0, width: 10, height: 10 }, display, null), null);
});

test("cropToRect is the inverse — source-px crop -> display-px overlay box", () => {
  const display = { width: 280, height: 140 };
  const source = { width: 1280, height: 640 };
  assert.deepEqual(L.cropToRect({ x: 320, y: 160, width: 640, height: 320 }, display, source), {
    left: 70, top: 35, width: 140, height: 70,
  });
  // clamps an over-large crop to the display box
  const r = L.cropToRect({ x: 0, y: 0, width: 99999, height: 99999 }, display, source);
  assert.deepEqual(r, { left: 0, top: 0, width: 280, height: 140 });
  // not drawable without positive dims
  assert.equal(L.cropToRect({ x: 0, y: 0, width: 0, height: 0 }, display, source), null);
  assert.equal(L.cropToRect({ width: 10, height: 10 }, display, null), null);
});

test("rectToCrop and cropToRect round-trip within even-rounding tolerance", () => {
  const display = { width: 300, height: 200 };
  const source = { width: 600, height: 400 };
  const crop = L.rectToCrop({ left: 30, top: 20, width: 150, height: 100 }, display, source);
  const back = L.cropToRect(crop, display, source);
  // back-projected box lands within a pixel of the drawn rectangle
  assert.ok(Math.abs(back.left - 30) <= 1);
  assert.ok(Math.abs(back.top - 20) <= 1);
  assert.ok(Math.abs(back.width - 150) <= 1);
  assert.ok(Math.abs(back.height - 100) <= 1);
});

test("summarizeBeforeAfter reports size shrink + percent", () => {
  const before = { format: { size: "10485760", duration: "30" } }; // 10 MB
  const after = { format: { size: "3145728", duration: "30" } }; //  3 MB
  // duration unchanged → only the size segment shows the −70% delta
  assert.equal(L.summarizeBeforeAfter(before, after), "10 MB → 3.0 MB (−70%)");
});

test("summarizeBeforeAfter adds a duration segment when it changes", () => {
  const before = { format: { size: "2000000", duration: "30" } };
  const after = { format: { size: "1000000", duration: "15" } };
  const text = L.summarizeBeforeAfter(before, after);
  assert.match(text, /−50%/);
  assert.ok(text.includes("0:30 → 0:15"), text);
  assert.ok(text.includes(" · "), text); // both segments joined
});

test("summarizeBeforeAfter handles growth and equal sizes", () => {
  const grew = L.summarizeBeforeAfter(
    { format: { size: "1000000" } },
    { format: { size: "1500000" } }
  );
  assert.match(grew, /\(\+50%\)/);
  const same = L.summarizeBeforeAfter(
    { format: { size: "1000000" } },
    { format: { size: "1000000" } }
  );
  assert.match(same, /\(±0%\)/);
});

test("summarizeBeforeAfter falls back to output-only size, or null", () => {
  // no input probe → just the output size, no percent
  assert.equal(
    L.summarizeBeforeAfter(null, { format: { size: "524288" } }),
    "512 KB"
  );
  // nothing probeable → null (caller hides the line)
  assert.equal(L.summarizeBeforeAfter(null, null), null);
  assert.equal(L.summarizeBeforeAfter({ format: {} }, { format: {} }), null);
});

test("oddDimensionWarning flags an odd typed width and/or height", () => {
  // single odd field names just that dimension + its nearest even value
  assert.match(
    L.oddDimensionWarning("compress", { "compress-width": "321" }),
    /Odd dimension.*even numbers.*width 321 → 322/
  );
  assert.match(
    L.oddDimensionWarning("pad", { "pad-height": "1081" }),
    /Round height 1081 → 1082/
  );
  // both odd → plural noun and both fields listed in width,height order
  assert.equal(
    L.oddDimensionWarning("crop", { "crop-width": "161", "crop-height": "121" }),
    "Odd dimensions — most video codecs need even numbers. Round width 161 → 162 and height 121 → 122."
  );
});

test("oddDimensionWarning stays quiet on even, blank, or non-integer dims", () => {
  assert.equal(L.oddDimensionWarning("compress", { "compress-width": "320", "compress-height": "240" }), null);
  assert.equal(L.oddDimensionWarning("blur_pad", { "blur_pad-width": "", "blur_pad-height": "  " }), null);
  assert.equal(L.oddDimensionWarning("crop", {}), null);
  // decimals / garbage can't reliably be "made even", so don't nag about them
  assert.equal(L.oddDimensionWarning("compress", { "compress-width": "320.5" }), null);
  assert.equal(L.oddDimensionWarning("compress", { "compress-width": "abc" }), null);
  assert.equal(L.oddDimensionWarning("compress", { "compress-width": "0" }), null);
});

test("oddDimensionWarning only applies to re-encoding, size-sensitive tabs", () => {
  // PNG/GIF outputs tolerate odd dims, and width-only tabs aren't size-locked here
  assert.equal(L.oddDimensionWarning("waveform", { "waveform-width": "641", "waveform-height": "121" }), null);
  assert.equal(L.oddDimensionWarning("gif", { "gif-width": "481" }), null);
  assert.equal(L.oddDimensionWarning("convert", { "compress-width": "321" }), null);
  // the guarded set is exactly the H.264-re-encode tabs with W+H fields
  assert.deepEqual(L.EVEN_DIM_TABS, ["compress", "crop", "pad", "blur_pad"]);
});

test("buildCliCommand maps a simple input/output op with --flags and -y", () => {
  assert.equal(
    L.buildCliCommand("convert", {
      input: "in.mov",
      output: "out.mp4",
      vcodec: "libx264",
      acodec: "aac",
      overwrite: true,
    }),
    "ffmpeg-util convert in.mov out.mp4 --vcodec libx264 --acodec aac -y"
  );
});

test("buildCliCommand emits boolean flags bare and drops null/empty/false", () => {
  assert.equal(
    L.buildCliCommand("convert", {
      input: "in.mov",
      output: "out.mp4",
      vcodec: null,
      acodec: "",
      extract_audio: true,
      overwrite: true,
    }),
    "ffmpeg-util convert in.mov out.mp4 --extract-audio -y"
  );
  // a false boolean is omitted entirely
  assert.equal(
    L.buildCliCommand("trim", { input: "a.mp4", output: "b.mp4", reencode: false, overwrite: true }),
    "ffmpeg-util trim a.mp4 b.mp4 -y"
  );
});

test("buildCliCommand kebab-cases the subcommand and multi-word flags", () => {
  assert.equal(
    L.buildCliCommand("blur_pad", { input: "i.mp4", output: "o.mp4", width: 480, height: 480, sigma: 20, overwrite: true }),
    "ffmpeg-util blur-pad i.mp4 o.mp4 --width 480 --height 480 --sigma 20 -y"
  );
  assert.equal(
    L.buildCliCommand("compress", { input: "i.mp4", output: "o.mp4", crf: 28, target_size: 8, overwrite: true }),
    "ffmpeg-util compress i.mp4 o.mp4 --crf 28 --target-size 8 -y"
  );
});

test("buildCliCommand renames the diverging sidecar fields to their CLI flags", () => {
  // Fade tab body key `fade` -> --duration
  assert.equal(
    L.buildCliCommand("fade", { input: "i.mp4", output: "o.mp4", fade: 1.5, overwrite: true }),
    "ffmpeg-util fade i.mp4 o.mp4 --duration 1.5 -y"
  );
  // Transform tab body key `transform` -> --op
  assert.equal(
    L.buildCliCommand("transform", { input: "i.mp4", output: "o.mp4", transform: "rotate-cw", overwrite: true }),
    "ffmpeg-util transform i.mp4 o.mp4 --op rotate-cw -y"
  );
  // Loudnorm body key `target_i` -> --target
  assert.equal(
    L.buildCliCommand("loudnorm", { input: "i.mp4", output: "o.mp4", target_i: -16, overwrite: true }),
    "ffmpeg-util loudnorm i.mp4 o.mp4 --target=-16 -y"
  );
});

test("buildCliCommand uses --flag=value for negative numbers", () => {
  assert.equal(
    L.buildCliCommand("volume", { input: "i.mp4", output: "o.mp4", gain: -6, overwrite: true }),
    "ffmpeg-util volume i.mp4 o.mp4 --gain=-6 -y"
  );
  // a positive gain stays in the spaced form
  assert.equal(
    L.buildCliCommand("volume", { input: "i.mp4", output: "o.mp4", gain: 3, overwrite: true }),
    "ffmpeg-util volume i.mp4 o.mp4 --gain 3 -y"
  );
});

test("buildCliCommand quotes paths/values with spaces and empty strings", () => {
  assert.equal(
    L.buildCliCommand("convert", { input: "my clip.mov", output: "out dir/v.mp4", overwrite: true }),
    'ffmpeg-util convert "my clip.mov" "out dir/v.mp4" -y'
  );
});

test("buildCliCommand handles inputs-list ops with -o output", () => {
  assert.equal(
    L.buildCliCommand("concat", { inputs: ["a.mp4", "b.mp4"], output: "joined.mp4", overwrite: true }),
    "ffmpeg-util concat a.mp4 b.mp4 -o joined.mp4 -y"
  );
  assert.equal(
    L.buildCliCommand("hstack", { inputs: ["left.mp4", "right.mp4"], output: "o.mp4", overwrite: true }),
    "ffmpeg-util hstack left.mp4 right.mp4 -o o.mp4 -y"
  );
});

test("buildCliCommand places --audio after positionals for replace_audio", () => {
  assert.equal(
    L.buildCliCommand("replace_audio", {
      input: "v.mp4",
      audio: "track.mp3",
      output: "o.mp4",
      overwrite: true,
    }),
    "ffmpeg-util replace-audio v.mp4 o.mp4 --audio track.mp3 -y"
  );
});

test("keyboardAction maps Ctrl/Cmd+Enter to a run action", () => {
  assert.deepEqual(L.keyboardAction({ key: "Enter", ctrlKey: true }), { type: "run" });
  assert.deepEqual(L.keyboardAction({ key: "Enter", metaKey: true }), { type: "run" });
});

test("keyboardAction maps Ctrl/Cmd+]/. to next and [/, to previous", () => {
  assert.deepEqual(L.keyboardAction({ key: "]", ctrlKey: true }), { type: "switch", dir: 1 });
  assert.deepEqual(L.keyboardAction({ key: ".", metaKey: true }), { type: "switch", dir: 1 });
  assert.deepEqual(L.keyboardAction({ key: "[", ctrlKey: true }), { type: "switch", dir: -1 });
  assert.deepEqual(L.keyboardAction({ key: ",", metaKey: true }), { type: "switch", dir: -1 });
});

test("keyboardAction ignores keys without a Ctrl/Cmd modifier", () => {
  assert.equal(L.keyboardAction({ key: "Enter" }), null);
  assert.equal(L.keyboardAction({ key: "]", shiftKey: true }), null);
  assert.equal(L.keyboardAction({ key: "a", ctrlKey: true }), null);
  assert.equal(L.keyboardAction(null), null);
});

test("nextVisibleTab wraps forward and backward over visible tabs", () => {
  const tabs = ["convert", "trim", "compress"];
  assert.equal(L.nextVisibleTab(tabs, "convert", 1), "trim");
  assert.equal(L.nextVisibleTab(tabs, "compress", 1), "convert"); // wrap to start
  assert.equal(L.nextVisibleTab(tabs, "convert", -1), "compress"); // wrap to end
  assert.equal(L.nextVisibleTab(tabs, "trim", -1), "convert");
});

test("nextVisibleTab handles a current tab hidden by the filter, and an empty list", () => {
  const tabs = ["trim", "compress"]; // "convert" filtered out
  assert.equal(L.nextVisibleTab(tabs, "convert", 1), "trim"); // first when moving forward
  assert.equal(L.nextVisibleTab(tabs, "convert", -1), "compress"); // last when moving back
  assert.equal(L.nextVisibleTab([], "convert", 1), null);
});

// The canonical nav order from index.html — the category map must cover exactly
// these, each once. (Kept in sync with the <nav class="tabs"> buttons.)
const NAV_TABS = [
  "convert", "trim", "concat", "thumbnail", "compress", "gif", "speed", "transform",
  "crop", "mute", "replace_audio", "pad", "loop", "frames", "reverse", "volume",
  "fade", "grayscale", "invert", "loudnorm", "boomerang", "eq", "fps", "crop_aspect",
  "mono", "title", "waveform", "sample_rate", "hstack", "vstack", "blur_pad",
  "image_to_video", "autocrop",
];

test("TOOL_CATEGORIES partitions every nav tab into exactly one category", () => {
  const flat = L.TOOL_CATEGORIES.flatMap((c) => c.tabs);
  // no tab appears twice across categories
  assert.equal(new Set(flat).size, flat.length, "a tab is listed under two categories");
  // the category map and the nav cover the same set of tabs
  assert.deepEqual([...flat].sort(), [...NAV_TABS].sort());
});

test("groupTabs orders categories, keeps tab order, and drops empty groups", () => {
  const groups = L.groupTabs(NAV_TABS, L.TOOL_CATEGORIES);
  // category order is preserved and all categories are present for the full nav
  assert.deepEqual(groups.map((g) => g.name), L.TOOL_CATEGORIES.map((c) => c.name));
  // within a category, the configured tab order is kept
  const fx = groups.find((g) => g.name === "Video FX");
  assert.deepEqual(fx.tabs, ["transform", "speed", "fps", "loop", "reverse", "boomerang", "fade", "image_to_video"]);
  // a partial set keeps only the categories that still have a visible tab
  const some = L.groupTabs(["convert", "eq", "title"], L.TOOL_CATEGORIES);
  assert.deepEqual(some.map((g) => g.name), ["Convert", "Color", "Metadata"]);
  assert.deepEqual(some.find((g) => g.name === "Color").tabs, ["eq"]);
});

test("groupTabs accepts a Set and collects unknown tabs into 'Other'", () => {
  const groups = L.groupTabs(new Set(["convert", "brand_new"]), L.TOOL_CATEGORIES);
  assert.deepEqual(groups.map((g) => g.name), ["Convert", "Other"]);
  assert.deepEqual(groups.find((g) => g.name === "Other").tabs, ["brand_new"]);
  // empty / nullish input yields no groups
  assert.deepEqual(L.groupTabs([], L.TOOL_CATEGORIES), []);
  assert.deepEqual(L.groupTabs(null, L.TOOL_CATEGORIES), []);
});
