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
