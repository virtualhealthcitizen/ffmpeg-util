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
