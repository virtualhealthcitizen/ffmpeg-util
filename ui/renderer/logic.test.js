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
  // frames auto-suggest uses %04d — must resolve to first padded filename
  assert.deepEqual(L.previewKind("video.frame_%04d.png"), { kind: "image", path: "video.frame_0001.png" });
});

test("shouldShowCompare returns true only when both paths are previewable", () => {
  assert.equal(L.shouldShowCompare("in.mp4", "out.mp4"), true);
  assert.equal(L.shouldShowCompare("in.png", "out.jpg"), true);
  assert.equal(L.shouldShowCompare("in.mp4", "out.png"), true);  // video + image
  assert.equal(L.shouldShowCompare("in.mp3", "out.mp4"), false); // audio not previewable
  assert.equal(L.shouldShowCompare("in.mp4", "out.mp3"), false); // output not previewable
  assert.equal(L.shouldShowCompare("", "out.mp4"), false);
  assert.equal(L.shouldShowCompare(null, "out.mp4"), false);
  assert.equal(L.shouldShowCompare("in.mp4", null), false);
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
  // zero-padded patterns (%04d is the default for the frames output spec)
  assert.equal(L.previewPath("frame_%04d.png"), "frame_0001.png");
  assert.equal(L.previewPath("frame_%3d.png"), "frame_001.png");
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

test("reorderList moves an item and returns a new array", () => {
  const src = ["a", "b", "c", "d"];
  assert.deepEqual(L.reorderList(src, 0, 2), ["b", "c", "a", "d"]); // forward
  assert.deepEqual(L.reorderList(src, 3, 1), ["a", "d", "b", "c"]); // backward
  assert.deepEqual(L.reorderList(src, 1, 0), ["b", "a", "c", "d"]); // up one
  assert.deepEqual(src, ["a", "b", "c", "d"]); // original untouched
});

test("reorderList is a no-op (copy) for equal or out-of-range indices", () => {
  const src = ["a", "b", "c"];
  assert.deepEqual(L.reorderList(src, 1, 1), src); // self-drop
  assert.deepEqual(L.reorderList(src, 0, 5), src); // target off the end
  assert.deepEqual(L.reorderList(src, -1, 1), src); // from off the start
  assert.notEqual(L.reorderList(src, 1, 1), src); // but a fresh array, not the same ref
});

test("reorderList tolerates non-arrays", () => {
  assert.deepEqual(L.reorderList(null, 0, 1), []);
  assert.deepEqual(L.reorderList(undefined, 0, 1), []);
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

test("helpForTab returns a one-line hint for a known tab, '' for unknown", () => {
  const h = L.helpForTab("compress");
  assert.ok(h.length > 0);
  assert.ok(/CRF/i.test(h)); // mentions the tool's key option
  assert.equal(L.helpForTab("nope"), "");
  assert.equal(L.helpForTab(""), "");
  assert.equal(L.helpForTab(undefined), "");
});

test("auto_orient tab is in Video FX category and has aliases + help", () => {
  const fxGroup = L.TOOL_CATEGORIES.find((g) => g.name === "Video FX");
  assert.ok(fxGroup.tabs.includes("auto_orient"), "auto_orient should be in Video FX category");
  const tools = Object.keys(L.TOOL_ALIASES).map((tab) => ({
    tab,
    label: tab,
    keywords: L.TOOL_ALIASES[tab],
  }));
  assert.ok(L.filterTools("rotation", tools).includes("auto_orient"), "alias 'rotation' should match auto_orient");
  assert.ok(L.filterTools("sideways", tools).includes("auto_orient"), "alias 'sideways' should match auto_orient");
  assert.ok(L.helpForTab("auto_orient").length > 0, "auto_orient should have help text");
  const outputSpec = L.OUTPUT_SPECS["auto_orient"];
  assert.ok(outputSpec && outputSpec.tag === "oriented", "auto_orient OUTPUT_SPECS tag should be 'oriented'");
});

test("deinterlace tab is in Color category and has aliases + help", () => {
  const colorGroup = L.TOOL_CATEGORIES.find((g) => g.name === "Color");
  assert.ok(colorGroup.tabs.includes("deinterlace"), "deinterlace should be in Color category");
  const tools = Object.keys(L.TOOL_ALIASES).map((tab) => ({
    tab,
    label: tab,
    keywords: L.TOOL_ALIASES[tab],
  }));
  assert.ok(L.filterTools("yadif", tools).includes("deinterlace"), "alias 'yadif' should match deinterlace");
  assert.ok(L.filterTools("interlaced", tools).includes("deinterlace"), "alias 'interlaced' should match deinterlace");
  assert.ok(L.helpForTab("deinterlace").length > 0, "deinterlace should have help text");
});

test("TOOL_HELP covers every tab in TOOL_CATEGORIES with a concise string", () => {
  const allTabs = L.TOOL_CATEGORIES.flatMap((c) => c.tabs);
  assert.ok(allTabs.length >= 30);
  for (const tab of allTabs) {
    const h = L.helpForTab(tab);
    assert.ok(h && h.length > 0, `missing help for ${tab}`);
    assert.ok(h.length <= 160, `help for ${tab} too long (${h.length})`);
  }
  // No stray help keys for tabs that aren't in the nav.
  for (const tab of Object.keys(L.TOOL_HELP)) {
    assert.ok(allTabs.includes(tab), `help for unknown tab ${tab}`);
  }
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

test("xfade_concat is in Combine category and has aliases + help", () => {
  const combineGroup = L.TOOL_CATEGORIES.find((g) => g.name === "Combine");
  assert.ok(combineGroup.tabs.includes("xfade_concat"), "xfade_concat should be in Combine category");
  assert.ok(typeof L.TOOL_ALIASES["xfade_concat"] === "string", "xfade_concat should have an alias");
  assert.ok(L.helpForTab("xfade_concat").length > 0, "xfade_concat should have help text");
});

test("compatReport flags xfade_concat size mismatch", () => {
  const a = { w: 320, h: 240 };
  const b = { w: 640, h: 480 };
  assert.equal(L.compatReport("xfade_concat", [a, a]).ok, true);
  assert.match(L.compatReport("xfade_concat", [a, b]).message, /differ in size/);
  assert.equal(L.compatReport("xfade_concat", [a, b]).ok, false);
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

test("estimateOutput preview_clip clips to seconds when shorter than input", () => {
  assert.equal(L.estimateOutput("preview_clip", 30, { seconds: "5" }), "~0:05");
});

test("estimateOutput preview_clip uses input duration when shorter than requested seconds", () => {
  assert.equal(L.estimateOutput("preview_clip", 3, { seconds: "10" }), "~0:03");
});

test("estimateOutput trim_pct computes output duration from percentage range", () => {
  assert.equal(L.estimateOutput("trim_pct", 10, { "start-pct": "25", "end-pct": "75" }), "~0:05");
  assert.equal(L.estimateOutput("trim_pct", 10, { "start-pct": "0", "end-pct": "50" }), "~0:05");
  assert.equal(L.estimateOutput("trim_pct", 10, { "start-pct": "0", "end-pct": "100" }), "~0:10");
});

test("estimateOutput trim_pct returns null when start >= end", () => {
  assert.equal(L.estimateOutput("trim_pct", 10, { "start-pct": "50", "end-pct": "25" }), null);
  assert.equal(L.estimateOutput("trim_pct", 10, { "start-pct": "50", "end-pct": "50" }), null);
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

test("SLIDER_SPECS covers the expected tabs and has required fields", () => {
  const specs = L.SLIDER_SPECS;
  assert.ok(Array.isArray(specs), "SLIDER_SPECS is an array");
  const ids = specs.map((s) => s.id);
  assert.ok(ids.includes("volume-gain"), "has volume-gain");
  assert.ok(ids.includes("speed-factor"), "has speed-factor");
  assert.ok(ids.includes("eq-brightness"), "has eq-brightness");
  assert.ok(ids.includes("eq-contrast"), "has eq-contrast");
  assert.ok(ids.includes("eq-saturation"), "has eq-saturation");
  assert.ok(ids.includes("fade-duration"), "has fade-duration");
  assert.ok(ids.includes("loudnorm-target"), "has loudnorm-target");
  for (const s of specs) {
    assert.ok(typeof s.min === "number", `${s.id} has numeric min`);
    assert.ok(typeof s.max === "number", `${s.id} has numeric max`);
    assert.ok(typeof s.step === "number" && s.step > 0, `${s.id} has positive step`);
    assert.ok(typeof s.def === "number", `${s.id} has numeric def`);
    assert.ok(s.def >= s.min && s.def <= s.max, `${s.id} def is in [min,max]`);
    assert.ok(typeof s.unit === "string", `${s.id} has string unit`);
  }
});

test("formatSliderOut formats values with the correct unit suffix", () => {
  const volSpec = L.SLIDER_SPECS.find((s) => s.id === "volume-gain");
  assert.equal(L.formatSliderOut(volSpec, 0), "0 dB");
  assert.equal(L.formatSliderOut(volSpec, -6), "-6 dB");
  assert.equal(L.formatSliderOut(volSpec, 3.5), "3.5 dB");

  const speedSpec = L.SLIDER_SPECS.find((s) => s.id === "speed-factor");
  assert.equal(L.formatSliderOut(speedSpec, 1), "1×");
  assert.equal(L.formatSliderOut(speedSpec, 2), "2×");
  assert.equal(L.formatSliderOut(speedSpec, 0.5), "0.5×");

  const loudSpec = L.SLIDER_SPECS.find((s) => s.id === "loudnorm-target");
  assert.equal(L.formatSliderOut(loudSpec, -16), "-16 LUFS");
  assert.equal(L.formatSliderOut(loudSpec, -23), "-23 LUFS");

  const eqSpec = L.SLIDER_SPECS.find((s) => s.id === "eq-brightness");
  assert.equal(L.formatSliderOut(eqSpec, 0), "0");
  assert.equal(L.formatSliderOut(eqSpec, -0.5), "-0.5");
});

test("formatSliderOut handles floating-point noise gracefully", () => {
  const fadeSpec = L.SLIDER_SPECS.find((s) => s.id === "fade-duration");
  // 0.1+0.2 = 0.30000000000000004 in floating point
  assert.equal(L.formatSliderOut(fadeSpec, 0.1 + 0.2), "0.3s");
  assert.equal(L.formatSliderOut(fadeSpec, NaN), "");
  assert.equal(L.formatSliderOut(fadeSpec, Infinity), "");
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

test("SLIDER_SPECS includes sharpen-amount and denoise-strength", () => {
  const ids = L.SLIDER_SPECS.map((s) => s.id);
  assert.ok(ids.includes("sharpen-amount"), "SLIDER_SPECS has sharpen-amount");
  assert.ok(ids.includes("denoise-strength"), "SLIDER_SPECS has denoise-strength");
  const sa = L.SLIDER_SPECS.find((s) => s.id === "sharpen-amount");
  assert.ok(sa.min < 0, "sharpen-amount min is negative (allows softening)");
  assert.ok(sa.def > 0, "sharpen-amount default is positive (sharpens by default)");
  const ds = L.SLIDER_SPECS.find((s) => s.id === "denoise-strength");
  assert.ok(ds.min >= 1, "denoise-strength min >= 1");
  assert.ok(ds.def >= ds.min && ds.def <= ds.max, "denoise-strength default in range");
});

test("TOOL_CATEGORIES Color group contains sharpen and denoise", () => {
  const colorGroup = L.TOOL_CATEGORIES.find((g) => g.name === "Color");
  assert.ok(colorGroup, "Color category exists");
  assert.ok(colorGroup.tabs.includes("sharpen"), "Color group has sharpen");
  assert.ok(colorGroup.tabs.includes("denoise"), "Color group has denoise");
});

test("suggestOutputForTab uses correct tags for sharpen, denoise, and timecode", () => {
  assert.equal(L.suggestOutputForTab("in.mp4", "sharpen"), "in.sharp.mp4");
  assert.equal(L.suggestOutputForTab("in.mp4", "denoise"), "in.denoise.mp4");
  assert.equal(L.suggestOutputForTab("in.mp4", "timecode"), "in.tc.mp4");
});

test("TOOL_CATEGORIES includes timecode in Video FX", () => {
  const vfx = L.TOOL_CATEGORIES.find(g => g.name === "Video FX");
  assert.ok(vfx, "Video FX category exists");
  assert.ok(vfx.tabs.includes("timecode"), "Video FX includes timecode");
});

test("buildCliCommand handles timecode with font_size and position", () => {
  assert.equal(
    L.buildCliCommand("timecode", {
      input: "in.mp4",
      output: "in.tc.mp4",
      font_size: 36,
      position: "bottom-right",
      color: "yellow",
      overwrite: true,
    }),
    "ffmpeg-util timecode in.mp4 in.tc.mp4 --font-size 36 --position bottom-right --color yellow -y"
  );
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
  // Trim-silence body key `threshold_db` -> --threshold (NOT --threshold-db)
  assert.equal(
    L.buildCliCommand("trim_silence", { input: "i.mp4", output: "o.mp4", threshold_db: -50, min_duration: 0.5, overwrite: true }),
    "ffmpeg-util trim-silence i.mp4 o.mp4 --threshold=-50 --min-duration 0.5 -y"
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

test("buildCliCommand xfade_concat maps xfade_duration to --duration and xfade_offset to --offset", () => {
  // xfade_duration must become --duration (not --xfade-duration); xfade_offset becomes --offset
  assert.equal(
    L.buildCliCommand("xfade_concat", {
      inputs: ["a.mp4", "b.mp4"],
      output: "out.mp4",
      transition: "fade",
      xfade_duration: 1.0,
      xfade_offset: 29.0,
      overwrite: true,
    }),
    "ffmpeg-util xfade-concat a.mp4 b.mp4 -o out.mp4 --transition fade --duration 1 --offset 29 -y"
  );
  // null offset is omitted (sidecar auto-computes; user must supply --offset themselves)
  assert.equal(
    L.buildCliCommand("xfade_concat", {
      inputs: ["a.mp4", "b.mp4"],
      output: "out.mp4",
      transition: "wipeleft",
      xfade_duration: 0.5,
      xfade_offset: null,
      overwrite: true,
    }),
    "ffmpeg-util xfade-concat a.mp4 b.mp4 -o out.mp4 --transition wipeleft --duration 0.5 -y"
  );
});

test("TOOL_CATEGORIES Video FX includes blur_region", () => {
  const vfx = L.TOOL_CATEGORIES.find(g => g.name === "Video FX");
  assert.ok(vfx, "Video FX category exists");
  assert.ok(vfx.tabs.includes("blur_region"), "Video FX includes blur_region");
});

test("suggestOutputForTab uses .blurred tag for blur_region", () => {
  assert.equal(L.suggestOutputForTab("clip.mp4", "blur_region"), "clip.blurred.mp4");
});

test("buildCliCommand handles blur_region with x/y/width/height/sigma", () => {
  assert.equal(
    L.buildCliCommand("blur_region", {
      input: "in.mp4", output: "in.blurred.mp4",
      x: 10, y: 20, width: 80, height: 60, sigma: 15, overwrite: true,
    }),
    "ffmpeg-util blur-region in.mp4 in.blurred.mp4 --x 10 --y 20 --width 80 --height 60 --sigma 15 -y"
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

test("resolveTheme normalizes to a known theme, defaulting to dark", () => {
  assert.equal(L.resolveTheme("light"), "light");
  assert.equal(L.resolveTheme("dark"), "dark");
  assert.equal(L.resolveTheme("neon"), "dark");
  assert.equal(L.resolveTheme(undefined), "dark");
  assert.equal(L.resolveTheme(null), "dark");
});

test("nextTheme cycles dark <-> light (tolerant of bad input)", () => {
  assert.equal(L.nextTheme("dark"), "light");
  assert.equal(L.nextTheme("light"), "dark");
  assert.equal(L.nextTheme("bogus"), "light"); // treated as dark -> light
  assert.equal(L.nextTheme(undefined), "light");
});

test("themeToggleLabel advertises the theme a click switches to", () => {
  assert.equal(L.themeToggleLabel("dark"), "☀ Light");
  assert.equal(L.themeToggleLabel("light"), "☾ Dark");
  assert.equal(L.themeToggleLabel("bogus"), "☀ Light"); // bad value reads as dark
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
  "convert", "trim", "trim_pct", "concat", "thumbnail", "compress", "gif", "speed", "transform",
  "crop", "mute", "replace_audio", "pad", "loop", "frames", "scene_thumbs", "reverse", "volume",
  "fade", "grayscale", "invert", "timecode", "deinterlace", "sharpen", "denoise", "loudnorm", "boomerang", "eq", "fps", "crop_aspect",
  "mono", "title", "waveform", "sample_rate", "trim_silence", "hstack", "vstack", "xfade_concat", "pip", "blur_pad",
  "image_to_video", "autocrop", "remux", "preview_clip", "blur_region", "poster_frame", "auto_orient",
  "stabilize", "watermark", "hardsub", "pixfmt",
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
  assert.deepEqual(fx.tabs, ["transform", "auto_orient", "stabilize", "speed", "fps", "loop", "reverse", "boomerang", "fade", "image_to_video", "timecode", "watermark", "hardsub", "blur_region"]);
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

test("normalizeFavorites cleans the stored list", () => {
  assert.deepEqual(L.normalizeFavorites(["crop", "crop", "", null, "gif"]), ["crop", "gif"]);
  assert.deepEqual(L.normalizeFavorites(null), []);
  assert.deepEqual(L.normalizeFavorites("crop"), []); // non-array is ignored
});

test("toggleFavorite pins and unpins immutably, appending new pins", () => {
  const a = L.toggleFavorite([], "crop");
  assert.deepEqual(a, ["crop"]);
  const b = L.toggleFavorite(a, "gif");
  assert.deepEqual(b, ["crop", "gif"]);
  assert.deepEqual(a, ["crop"], "the original list is not mutated");
  assert.deepEqual(L.toggleFavorite(b, "crop"), ["gif"]); // unpin removes it
  assert.deepEqual(L.toggleFavorite(["crop"], ""), ["crop"]); // blank tab is a no-op
});

test("isFavorite reflects membership", () => {
  assert.equal(L.isFavorite(["crop", "gif"], "gif"), true);
  assert.equal(L.isFavorite(["crop"], "gif"), false);
  assert.equal(L.isFavorite(null, "gif"), false);
});

test("groupTabsWithFavorites leads with a Favorites row and de-dupes categories", () => {
  const groups = L.groupTabsWithFavorites(NAV_TABS, ["gif", "crop"], L.TOOL_CATEGORIES);
  // the Favorites group is first, in favorites order
  assert.equal(groups[0].name, L.FAVORITES_GROUP);
  assert.deepEqual(groups[0].tabs, ["gif", "crop"]);
  // pinned tabs are removed from their normal categories
  assert.ok(!groups.find((g) => g.name === "Trim & Frames").tabs.includes("gif"));
  assert.ok(!groups.find((g) => g.name === "Resize & Frame").tabs.includes("crop"));
  // every nav tab still appears exactly once across all groups
  const flat = groups.flatMap((g) => g.tabs);
  assert.equal(new Set(flat).size, flat.length);
  assert.deepEqual([...flat].sort(), [...NAV_TABS].sort());
});

test("groupTabsWithFavorites with no/absent favorites matches groupTabs", () => {
  assert.deepEqual(
    L.groupTabsWithFavorites(NAV_TABS, [], L.TOOL_CATEGORIES),
    L.groupTabs(NAV_TABS, L.TOOL_CATEGORIES)
  );
  // only *present* favorites appear — a filtered-away pin drops out of the row
  const groups = L.groupTabsWithFavorites(["convert", "gif"], ["gif", "crop"], L.TOOL_CATEGORIES);
  assert.deepEqual(groups[0].tabs, ["gif"]); // crop isn't present → excluded
});

test("addRecentFile prepends, dedups case-insensitively, caps the list", () => {
  // new path goes to the front
  assert.deepEqual(L.addRecentFile(["a.mp4"], "b.mp4"), ["b.mp4", "a.mp4"]);
  // re-loading an existing path moves it to the front (keeps the newest casing)
  assert.deepEqual(L.addRecentFile(["a.mp4", "b.mp4"], "A.MP4"), ["A.MP4", "b.mp4"]);
  // empty/whitespace paths are ignored (just sanitized list back)
  assert.deepEqual(L.addRecentFile(["a.mp4"], "   "), ["a.mp4"]);
  // non-array / junk entries are tolerated
  assert.deepEqual(L.addRecentFile(null, "a.mp4"), ["a.mp4"]);
  assert.deepEqual(L.addRecentFile([1, "", "a.mp4"], "b.mp4"), ["b.mp4", "a.mp4"]);
  // capped at max, newest first
  assert.deepEqual(L.addRecentFile(["a", "b", "c"], "d", 2), ["d", "a"]);
});

test("recentFileLabel returns the basename for Windows and POSIX paths", () => {
  assert.equal(L.recentFileLabel("C:\\videos\\clip.mp4"), "clip.mp4");
  assert.equal(L.recentFileLabel("/home/u/clip.mp4"), "clip.mp4");
  assert.equal(L.recentFileLabel("clip.mp4"), "clip.mp4");
  assert.equal(L.recentFileLabel(""), "");
});

test("recentDir returns the most-recent entry's directory without a trailing sep", () => {
  assert.equal(L.recentDir(["C:\\videos\\clip.mp4", "C:\\other\\x.mp4"]), "C:\\videos");
  assert.equal(L.recentDir(["/home/u/clip.mp4"]), "/home/u");
  assert.equal(L.recentDir([]), "");
  assert.equal(L.recentDir(["noslash.mp4"]), "");
});

test("setRecentOutput records the last output path per tab", () => {
  assert.deepEqual(L.setRecentOutput({}, "compress", "C:\\out\\v.mp4"), { compress: "C:\\out\\v.mp4" });
  assert.deepEqual(L.setRecentOutput(null, "gif", "x.gif"), { gif: "x.gif" });
  // overwrites previous entry for same tab
  assert.deepEqual(L.setRecentOutput({ compress: "old.mp4" }, "compress", "new.mp4"), { compress: "new.mp4" });
  // preserves other tabs
  assert.deepEqual(L.setRecentOutput({ gif: "a.gif" }, "compress", "b.mp4"), { gif: "a.gif", compress: "b.mp4" });
  // empty/whitespace path → unchanged
  assert.deepEqual(L.setRecentOutput({ a: "x.mp4" }, "compress", "   "), { a: "x.mp4" });
  // missing tab → unchanged
  assert.deepEqual(L.setRecentOutput({ a: "x.mp4" }, "", "new.mp4"), { a: "x.mp4" });
});

test("recentOutputDir extracts the directory of the last output for a tab", () => {
  assert.equal(L.recentOutputDir({ compress: "C:\\out\\v.mp4" }, "compress"), "C:\\out");
  assert.equal(L.recentOutputDir({ compress: "/home/u/out.mp4" }, "compress"), "/home/u");
  assert.equal(L.recentOutputDir({}, "compress"), "");
  assert.equal(L.recentOutputDir(null, "gif"), "");
  assert.equal(L.recentOutputDir({ compress: "nodir.mp4" }, "compress"), "");
  // tab not in dict → ""
  assert.equal(L.recentOutputDir({ gif: "a.gif" }, "compress"), "");
});

test("parseSpeed reads ffmpeg's speed field, rejecting junk", () => {
  assert.equal(L.parseSpeed("1.05x"), 1.05);
  assert.equal(L.parseSpeed("0.5x"), 0.5);
  assert.equal(L.parseSpeed("2x"), 2);
  assert.equal(L.parseSpeed("  1.5 x "), 1.5);
  assert.equal(L.parseSpeed("N/A"), null);
  assert.equal(L.parseSpeed("0x"), null);
  assert.equal(L.parseSpeed(null), null);
  assert.equal(L.parseSpeed(undefined), null);
});

test("etaSeconds = remaining output seconds / speed", () => {
  // 10s output, at 2s in, encoding 2x -> (10-2)/2 = 4s remaining
  assert.equal(L.etaSeconds({ total: 10, out_time: 2, speed: "2x" }), 4);
  // half-speed doubles the wait
  assert.equal(L.etaSeconds({ total: 10, out_time: 0, speed: "0.5x" }), 20);
  // at/over the end clamps remaining to 0
  assert.equal(L.etaSeconds({ total: 10, out_time: 12, speed: "1x" }), 0);
});

test("etaSeconds returns null until inputs are usable", () => {
  assert.equal(L.etaSeconds(null), null);
  assert.equal(L.etaSeconds({ total: null, out_time: 1, speed: "1x" }), null);
  assert.equal(L.etaSeconds({ total: 0, out_time: 0, speed: "1x" }), null);
  assert.equal(L.etaSeconds({ total: 10, out_time: 1, speed: "N/A" }), null);
  assert.equal(L.etaSeconds({ total: 10, out_time: 1 }), null); // no speed
});

test("etaLabel formats the remaining time, or null when not predictable", () => {
  assert.equal(L.etaLabel({ total: 100, out_time: 10, speed: "1x" }), "ETA ~1:30");
  assert.equal(L.etaLabel({ total: 10, out_time: 2, speed: "2x" }), "ETA ~0:04");
  assert.equal(L.etaLabel({ total: 10, out_time: 1, speed: "N/A" }), null);
});

test("appendConsoleLines appends, splits on newlines, and caps the buffer", () => {
  assert.deepEqual(L.appendConsoleLines([], "first"), ["first"]);
  assert.deepEqual(L.appendConsoleLines(["a"], "b"), ["a", "b"]);
  // a multi-line chunk becomes multiple lines
  assert.deepEqual(L.appendConsoleLines(["a"], "b\nc"), ["a", "b", "c"]);
  // capped to the last `max` lines
  const many = [];
  let buf = [];
  for (let i = 0; i < 10; i++) buf = L.appendConsoleLines(buf, "L" + i, 3);
  assert.deepEqual(buf, ["L7", "L8", "L9"]);
  // null/undefined are tolerated (become an empty line, never throw)
  assert.deepEqual(L.appendConsoleLines(["a"], null), ["a", ""]);
});

test("revealLabel returns the right label per platform", () => {
  assert.equal(L.revealLabel("win32"), "Reveal in Explorer");
  assert.equal(L.revealLabel("darwin"), "Reveal in Finder");
  assert.equal(L.revealLabel("linux"), "Reveal in Files");
  assert.equal(L.revealLabel("freebsd"), "Reveal in Explorer"); // unknown → Explorer
  assert.equal(L.revealLabel(null), "Reveal in Explorer");
  assert.equal(L.revealLabel(undefined), "Reveal in Explorer");
});

test("outputBaseName extracts filename from Windows, POSIX, and bare paths", () => {
  assert.equal(L.outputBaseName("C:\\Users\\james\\out.mp4"), "out.mp4");
  assert.equal(L.outputBaseName("/tmp/out.gif"), "out.gif");
  assert.equal(L.outputBaseName("out.mp4"), "out.mp4");
  assert.equal(L.outputBaseName(null), null);
  assert.equal(L.outputBaseName(""), null);
});

test("runInputEntries maps body inputs to [path, fieldId] pairs", () => {
  // single-input tab
  assert.deepEqual(L.runInputEntries("compress", { input: "in.mp4", output: "out.mp4" }),
    [["in.mp4", "compress-input"]]);
  // multi-input concat: all paths map to the shared textarea id
  assert.deepEqual(L.runInputEntries("concat", { inputs: ["a.mp4", "b.mp4"] }),
    [["a.mp4", "concat-inputs"], ["b.mp4", "concat-inputs"]]);
  // hstack/vstack: separate field per slot
  assert.deepEqual(L.runInputEntries("hstack", { inputs: ["a.mp4", "b.mp4"] }),
    [["a.mp4", "hstack-input-a"], ["b.mp4", "hstack-input-b"]]);
  assert.deepEqual(L.runInputEntries("vstack", { inputs: ["x.mp4", "y.mp4"] }),
    [["x.mp4", "vstack-input-a"], ["y.mp4", "vstack-input-b"]]);
  // replace_audio has TWO input paths: the video (input) and the audio file (audio)
  assert.deepEqual(
    L.runInputEntries("replace_audio", { input: "vid.mp4", audio: "track.mp3", output: "out.mp4" }),
    [["vid.mp4", "replace_audio-input"], ["track.mp3", "replace_audio-audio"]],
  );
  // only non-empty paths are included
  assert.deepEqual(
    L.runInputEntries("replace_audio", { input: "vid.mp4", audio: "", output: "out.mp4" }),
    [["vid.mp4", "replace_audio-input"]],
  );
  // empty input is dropped (requireFields catches these before run starts)
  assert.deepEqual(L.runInputEntries("compress", { input: "", output: "out.mp4" }), []);
  // missing body
  assert.deepEqual(L.runInputEntries("compress", null), []);
});

test("fieldTooltip returns a non-empty string for known fields, '' for unknown", () => {
  // a few representative covered fields
  const crf = L.fieldTooltip("compress-crf");
  assert.ok(crf.length > 0, "compress-crf has a tooltip");
  assert.ok(/CRF|Rate Factor/i.test(crf), "compress-crf mentions CRF");

  const loop = L.fieldTooltip("gif-loop");
  assert.ok(loop.length > 0, "gif-loop has a tooltip");
  assert.ok(/infinite|loop/i.test(loop), "gif-loop mentions loop behaviour");

  // unknown ids return ""
  assert.equal(L.fieldTooltip("compress-input"), "");
  assert.equal(L.fieldTooltip("nope"), "");
  assert.equal(L.fieldTooltip(""), "");
  assert.equal(L.fieldTooltip(undefined), "");
});

test("FIELD_TOOLTIPS has no path fields (input/output keys are excluded)", () => {
  for (const id of Object.keys(L.FIELD_TOOLTIPS)) {
    assert.ok(
      !L.isPathFieldId(id),
      `FIELD_TOOLTIPS should not include path field "${id}"`
    );
  }
});

test("concat-reencode tooltip exists and is about re-encoding", () => {
  const tip = L.fieldTooltip("concat-reencode");
  assert.ok(tip.length > 0, "concat-reencode has a tooltip");
  assert.ok(/re.encod|codec|size/i.test(tip), "concat-reencode tooltip mentions codec or size");
});

test("FIELD_TOOLTIPS entries are concise (≤ 160 chars) and non-empty", () => {
  for (const [id, text] of Object.entries(L.FIELD_TOOLTIPS)) {
    assert.ok(text && text.length > 0, `tooltip for "${id}" must not be empty`);
    assert.ok(text.length <= 160, `tooltip for "${id}" too long (${text.length})`);
  }
});

test("notifyComplete returns null when disabled", () => {
  assert.equal(L.notifyComplete("out.mp4", false), null);
  assert.equal(L.notifyComplete(null, false), null);
});

test("notifyComplete returns { title, body } with filename when enabled", () => {
  const result = L.notifyComplete("out.mp4", true);
  assert.deepEqual(result, { title: "ffmpeg-util", body: "Done — out.mp4" });
});

test("notifyComplete returns a generic body when basename is falsy", () => {
  assert.deepEqual(L.notifyComplete(null, true), { title: "ffmpeg-util", body: "Done." });
  assert.deepEqual(L.notifyComplete("", true), { title: "ffmpeg-util", body: "Done." });
});

test("runOutputDirEntry returns [dir, fieldId] or null", () => {
  // Windows path with directory component
  const winEntry = L.runOutputDirEntry("compress", { output: "C:\\foo\\bar.mp4" });
  assert.ok(winEntry !== null);
  assert.equal(winEntry[0], "C:\\foo\\");
  assert.equal(winEntry[1], "compress-output");
  // POSIX path with directory component
  const posixEntry = L.runOutputDirEntry("gif", { output: "/tmp/out.gif" });
  assert.ok(posixEntry !== null);
  assert.equal(posixEntry[0], "/tmp/");
  assert.equal(posixEntry[1], "gif-output");
  // bare filename (no dir) → null (cwd always exists, nothing to check)
  assert.equal(L.runOutputDirEntry("compress", { output: "bar.mp4" }), null);
  // no output → null
  assert.equal(L.runOutputDirEntry("compress", { output: "" }), null);
  assert.equal(L.runOutputDirEntry("compress", {}), null);
});

test("trim_silence is in OUTPUT_SPECS with tag 'trimmed'", () => {
  const spec = L.OUTPUT_SPECS["trim_silence"];
  assert.ok(spec, "trim_silence must be in OUTPUT_SPECS");
  assert.equal(spec.tag, "trimmed");
});

test("trim_silence is in TOOL_CATEGORIES Audio group", () => {
  const audio = L.TOOL_CATEGORIES.find((c) => c.name === "Audio");
  assert.ok(audio, "Audio category must exist");
  assert.ok(audio.tabs.includes("trim_silence"), "trim_silence must be in Audio tabs");
});

test("helpForTab returns non-empty help for trim_silence", () => {
  const h = L.helpForTab("trim_silence");
  assert.ok(h && h.length > 0, "trim_silence must have a help entry");
});

test("TOOL_ALIASES has a non-empty entry for trim_silence", () => {
  const alias = L.TOOL_ALIASES["trim_silence"];
  assert.ok(alias && alias.length > 0, "trim_silence must have aliases");
  assert.ok(alias.includes("silence"), "alias must include 'silence'");
});

test("fieldTooltip returns non-empty blurbs for trim_silence fields", () => {
  assert.ok(L.fieldTooltip("trim_silence-threshold").length > 0);
  assert.ok(L.fieldTooltip("trim_silence-min-duration").length > 0);
});

test("suggestOutputForTab uses 'trimmed' tag for trim_silence", () => {
  const out = L.suggestOutputForTab("C:\\clips\\rec.mp3", "trim_silence");
  assert.ok(out.includes("trimmed"), "output path should contain 'trimmed' tag");
});

test("suggestOutputForTab uses 'remux' tag and keeps input extension", () => {
  assert.equal(L.suggestOutputForTab("in.mkv", "remux"), "in.remux.mkv");
  assert.equal(L.suggestOutputForTab("clip.mp4", "remux"), "clip.remux.mp4");
});

test("TOOL_ALIASES includes remux with container keywords", () => {
  assert.ok(L.TOOL_ALIASES.remux, "remux should have aliases");
  assert.ok(L.TOOL_ALIASES.remux.includes("container"));
  assert.ok(L.TOOL_ALIASES.remux.includes("mkv"));
});

test("scene_thumbs is in OUTPUT_SPECS with .png extension and %04d tag", () => {
  const spec = L.OUTPUT_SPECS["scene_thumbs"];
  assert.ok(spec, "scene_thumbs must be in OUTPUT_SPECS");
  assert.ok(spec.tag.includes("%04d"), "tag must include %04d");
  assert.equal(spec.ext, ".png");
});

test("suggestOutputForTab generates a %04d pattern for scene_thumbs", () => {
  const out = L.suggestOutputForTab("C:\\clips\\movie.mp4", "scene_thumbs");
  assert.ok(out.includes("scene_"), "output path should contain 'scene_' tag");
  assert.ok(out.endsWith(".png"), "output should be a .png file");
});

test("scene_thumbs is in TOOL_CATEGORIES Trim & Frames group", () => {
  const grp = L.TOOL_CATEGORIES.find((c) => c.name === "Trim & Frames");
  assert.ok(grp, "Trim & Frames category must exist");
  assert.ok(grp.tabs.includes("scene_thumbs"), "scene_thumbs must be in Trim & Frames");
});

test("helpForTab returns non-empty help for scene_thumbs", () => {
  const h = L.helpForTab("scene_thumbs");
  assert.ok(h && h.length > 0, "scene_thumbs must have a help entry");
});

test("TOOL_ALIASES has scene detection keywords for scene_thumbs", () => {
  const alias = L.TOOL_ALIASES["scene_thumbs"];
  assert.ok(alias && alias.length > 0, "scene_thumbs must have aliases");
  assert.ok(alias.includes("scene"), "alias must include 'scene'");
});

test("fieldTooltip returns non-empty blurbs for scene_thumbs fields", () => {
  assert.ok(L.fieldTooltip("scene_thumbs-threshold").length > 0);
  assert.ok(L.fieldTooltip("scene_thumbs-width").length > 0);
});

test("stabilize is in OUTPUT_SPECS with tag 'stable'", () => {
  const spec = L.OUTPUT_SPECS["stabilize"];
  assert.ok(spec, "stabilize must be in OUTPUT_SPECS");
  assert.equal(spec.tag, "stable");
});

test("stabilize is in TOOL_CATEGORIES Video FX group", () => {
  const grp = L.TOOL_CATEGORIES.find((c) => c.name === "Video FX");
  assert.ok(grp, "Video FX category must exist");
  assert.ok(grp.tabs.includes("stabilize"), "stabilize must be in Video FX tabs");
});

test("helpForTab returns non-empty help for stabilize", () => {
  const h = L.helpForTab("stabilize");
  assert.ok(h && h.length > 0, "stabilize must have a help entry");
  assert.ok(h.includes("vidstab"), "help must mention vidstab");
});

test("TOOL_ALIASES has shake/steady keywords for stabilize", () => {
  const alias = L.TOOL_ALIASES["stabilize"];
  assert.ok(alias && alias.length > 0, "stabilize must have aliases");
  assert.ok(alias.includes("shaky"), "alias must include 'shaky'");
  assert.ok(alias.includes("smooth"), "alias must include 'smooth'");
});

test("fieldTooltip returns non-empty blurbs for stabilize fields", () => {
  assert.ok(L.fieldTooltip("stabilize-shakiness").length > 0, "shakiness tooltip must exist");
  assert.ok(L.fieldTooltip("stabilize-smoothing").length > 0, "smoothing tooltip must exist");
});

test("suggestOutputForTab uses 'stable' tag for stabilize", () => {
  const out = L.suggestOutputForTab("C:\\clips\\handheld.mp4", "stabilize");
  assert.ok(out.includes("stable"), "output path should contain 'stable' tag");
});

// --- validateField ---

test("validateField returns null for empty or blank values (always valid)", () => {
  assert.equal(L.validateField("compress-crf", ""), null);
  assert.equal(L.validateField("trim-start", ""), null);
  assert.equal(L.validateField("volume-gain", "  "), null);
  assert.equal(L.validateField("gif-fps", ""), null);
});

test("validateField returns null for unknown field ids", () => {
  assert.equal(L.validateField("no-such-field", "999"), null);
  assert.equal(L.validateField("compress-input", "bad/path"), null);
  assert.equal(L.validateField("", "0"), null);
});

test("validateField validates CRF range 0–51", () => {
  assert.equal(L.validateField("compress-crf", "28"), null);
  assert.equal(L.validateField("compress-crf", "0"), null);
  assert.equal(L.validateField("compress-crf", "51"), null);
  assert.ok(L.validateField("compress-crf", "52") !== null, "52 is out of range");
  assert.ok(L.validateField("compress-crf", "-1") !== null, "negative is invalid");
  assert.ok(L.validateField("compress-crf", "1.5") !== null, "float is invalid");
});

test("validateField validates timecode fields", () => {
  assert.equal(L.validateField("trim-start", "5"), null);
  assert.equal(L.validateField("trim-start", "00:01:30"), null);
  assert.equal(L.validateField("trim-end", "1:30.5"), null);
  assert.ok(L.validateField("trim-start", "abc") !== null, "non-numeric is invalid");
  assert.ok(L.validateField("gif-duration", "not:a:timecode:extra") !== null, "4-part is invalid");
});

test("validateField validates gif-fps (must be positive integer)", () => {
  assert.equal(L.validateField("gif-fps", "12"), null);
  assert.equal(L.validateField("gif-fps", "1"), null);
  assert.ok(L.validateField("gif-fps", "0") !== null, "0 is invalid");
  assert.ok(L.validateField("gif-fps", "2.5") !== null, "float is invalid");
});

test("validateField validates gif-loop (integer ≥ −1)", () => {
  assert.equal(L.validateField("gif-loop", "0"), null);
  assert.equal(L.validateField("gif-loop", "-1"), null);
  assert.equal(L.validateField("gif-loop", "5"), null);
  assert.ok(L.validateField("gif-loop", "-2") !== null, "-2 is invalid");
  assert.ok(L.validateField("gif-loop", "1.5") !== null, "float is invalid");
});

test("validateField validates slider-backed fields against SLIDER_SPECS range", () => {
  assert.equal(L.validateField("volume-gain", "0"), null);
  assert.equal(L.validateField("volume-gain", "-60"), null);
  assert.equal(L.validateField("volume-gain", "30"), null);
  assert.ok(L.validateField("volume-gain", "31") !== null, "31 dB exceeds max");
  assert.ok(L.validateField("volume-gain", "-61") !== null, "-61 dB below min");
  assert.equal(L.validateField("speed-factor", "1"), null);
  assert.ok(L.validateField("speed-factor", "0") !== null, "0× is below min");
});

test("validateField validates poster_frame-percent and trim_pct percentages", () => {
  assert.equal(L.validateField("poster_frame-percent", "50"), null);
  assert.equal(L.validateField("poster_frame-percent", "0"), null);
  assert.equal(L.validateField("poster_frame-percent", "100"), null);
  assert.ok(L.validateField("poster_frame-percent", "101") !== null, "101 out of range");
  assert.equal(L.validateField("trim_pct-start-pct", "0"), null);
  assert.equal(L.validateField("trim_pct-start-pct", "99"), null);
  assert.ok(L.validateField("trim_pct-start-pct", "100") !== null, "100 exceeds max 99");
  assert.equal(L.validateField("trim_pct-end-pct", "1"), null);
  assert.equal(L.validateField("trim_pct-end-pct", "100"), null);
  assert.ok(L.validateField("trim_pct-end-pct", "0") !== null, "0 below min 1");
});

test("watermark: OUTPUT_SPECS has wm tag", () => {
  assert.equal(L.OUTPUT_SPECS.watermark.tag, "wm");
});

test("watermark: TOOL_HELP has non-empty entry", () => {
  const help = L.helpForTab("watermark");
  assert.ok(help && help.length > 0, "watermark should have a help string");
  assert.ok(help.includes("watermark") || help.includes("text"), "help should mention watermark or text");
});

test("watermark: TOOL_CATEGORIES includes watermark in Video FX", () => {
  const vfx = L.TOOL_CATEGORIES.find((c) => c.name === "Video FX");
  assert.ok(vfx, "Video FX category should exist");
  assert.ok(vfx.tabs.includes("watermark"), "watermark should be in Video FX");
});

test("watermark: FIELD_TOOLTIPS has entries for watermark fields", () => {
  assert.ok(L.fieldTooltip("watermark-text").length > 0, "watermark-text tooltip missing");
  assert.ok(L.fieldTooltip("watermark-font-size").length > 0, "watermark-font-size tooltip missing");
  assert.ok(L.fieldTooltip("watermark-opacity").length > 0, "watermark-opacity tooltip missing");
  assert.ok(L.fieldTooltip("watermark-position").length > 0, "watermark-position tooltip missing");
  assert.ok(L.fieldTooltip("watermark-color").length > 0, "watermark-color tooltip missing");
});

test("watermark: SLIDER_SPECS includes watermark-font-size and watermark-opacity", () => {
  const ids = L.SLIDER_SPECS.map((s) => s.id);
  assert.ok(ids.includes("watermark-font-size"), "SLIDER_SPECS should include watermark-font-size");
  assert.ok(ids.includes("watermark-opacity"), "SLIDER_SPECS should include watermark-opacity");
  const opSpec = L.SLIDER_SPECS.find((s) => s.id === "watermark-opacity");
  assert.equal(opSpec.min, 0);
  assert.equal(opSpec.max, 1);
});

test("watermark: buildCliCommand produces correct command", () => {
  const cmd = L.buildCliCommand("watermark", {
    input: "in.mp4", output: "in.wm.mp4",
    text: "© 2024", font_size: 24, opacity: 0.8,
    position: "bottom-right", color: "white", overwrite: true,
  });
  assert.ok(cmd.startsWith("ffmpeg-util watermark"), "should start with ffmpeg-util watermark");
  assert.ok(cmd.includes("in.mp4"), "should include input");
  assert.ok(cmd.includes("--font-size 24"), "should include --font-size");
  assert.ok(cmd.includes("--opacity 0.8"), "should include --opacity");
  assert.ok(cmd.includes("-y"), "overwrite flag should append -y");
});

test("watermark: validateField validates watermark-opacity via SLIDER_SPECS", () => {
  assert.equal(L.validateField("watermark-opacity", "0"), null);
  assert.equal(L.validateField("watermark-opacity", "1"), null);
  assert.equal(L.validateField("watermark-opacity", "0.5"), null);
  assert.ok(L.validateField("watermark-opacity", "1.1") !== null, "1.1 exceeds max 1");
  assert.ok(L.validateField("watermark-opacity", "-0.1") !== null, "-0.1 below min 0");
});

test("hardsub: OUTPUT_SPECS has sub tag", () => {
  assert.equal(L.OUTPUT_SPECS.hardsub.tag, "sub");
});

test("hardsub: TOOL_HELP has non-empty entry", () => {
  const help = L.helpForTab("hardsub");
  assert.ok(help && help.length > 0, "hardsub should have a help string");
  assert.ok(help.includes("subtitle") || help.includes("hardsub"), "help should mention subtitle or hardsub");
});

test("hardsub: TOOL_CATEGORIES includes hardsub in Video FX", () => {
  const vfx = L.TOOL_CATEGORIES.find((c) => c.name === "Video FX");
  assert.ok(vfx, "Video FX category should exist");
  assert.ok(vfx.tabs.includes("hardsub"), "hardsub should be in Video FX");
});

test("hardsub: runInputEntries returns both video and subtitle entries", () => {
  const entries = L.runInputEntries("hardsub", {
    input: "/videos/clip.mp4",
    subtitle: "/subs/movie.srt",
    output: "/out/clip.sub.mp4",
  });
  const fields = entries.map(([, id]) => id);
  assert.ok(fields.includes("hardsub-input"), "should include hardsub-input field");
  assert.ok(fields.includes("hardsub-subtitle"), "should include hardsub-subtitle field");
});

test("hardsub: buildCliCommand produces correct command", () => {
  const cmd = L.buildCliCommand("hardsub", {
    input: "clip.mp4",
    subtitle: "movie.srt",
    output: "clip.sub.mp4",
    overwrite: true,
  });
  assert.ok(cmd.startsWith("ffmpeg-util hardsub"), "should start with ffmpeg-util hardsub");
  assert.ok(cmd.includes("--subtitle"), "should include --subtitle flag");
  assert.ok(cmd.includes("movie.srt"), "should include subtitle path");
});

test("pip: OUTPUT_SPECS has pip tag", () => {
  assert.ok(L.OUTPUT_SPECS.pip, "pip should be in OUTPUT_SPECS");
  assert.equal(L.OUTPUT_SPECS.pip.tag, "pip");
});

test("pip: TOOL_CATEGORIES includes pip in Combine", () => {
  const combine = L.TOOL_CATEGORIES.find((c) => c.name === "Combine");
  assert.ok(combine, "Combine category should exist");
  assert.ok(combine.tabs.includes("pip"), "pip should be in Combine");
});

test("pip: helpForTab returns non-empty string", () => {
  const h = L.helpForTab("pip");
  assert.ok(typeof h === "string" && h.length > 0, "pip should have help text");
});

test("pip: runInputEntries returns both input and overlay entries", () => {
  const entries = L.runInputEntries("pip", {
    input: "/videos/base.mp4",
    overlay: "/videos/overlay.mp4",
    output: "/out/pip.mp4",
  });
  const fields = entries.map(([, id]) => id);
  assert.ok(fields.includes("pip-input"), "should include pip-input field");
  assert.ok(fields.includes("pip-overlay"), "should include pip-overlay field");
});

test("pip: buildCliCommand maps pip_size to --size flag", () => {
  const cmd = L.buildCliCommand("pip", {
    input: "base.mp4",
    overlay: "ov.mp4",
    output: "out.mp4",
    pip_size: 30,
    position: "top-right",
    overwrite: true,
  });
  assert.ok(cmd.startsWith("ffmpeg-util pip"), "should start with ffmpeg-util pip");
  assert.ok(cmd.includes("--size"), "pip_size should map to --size");
  assert.ok(cmd.includes("30"), "size value should appear");
  assert.ok(cmd.includes("--overlay"), "overlay path should use --overlay flag");
  assert.ok(cmd.includes("--position"), "position should appear");
});

test("pixfmt: OUTPUT_SPECS has pixfmt tag", () => {
  assert.ok(L.OUTPUT_SPECS.pixfmt, "pixfmt should be in OUTPUT_SPECS");
  assert.equal(L.OUTPUT_SPECS.pixfmt.tag, "pixfmt");
});

test("pixfmt: TOOL_CATEGORIES includes pixfmt in Convert", () => {
  const convert = L.TOOL_CATEGORIES.find((c) => c.name === "Convert");
  assert.ok(convert, "Convert category should exist");
  assert.ok(convert.tabs.includes("pixfmt"), "pixfmt should be in Convert");
});

test("pixfmt: helpForTab returns non-empty string mentioning format", () => {
  const h = L.helpForTab("pixfmt");
  assert.ok(typeof h === "string" && h.length > 0, "pixfmt should have help text");
  assert.ok(h.includes("pixel") || h.includes("format"), "help should mention pixel or format");
});

test("pixfmt: buildCliCommand produces correct command with --pix-fmt flag", () => {
  const cmd = L.buildCliCommand("pixfmt", {
    input: "clip.mp4",
    output: "clip.pixfmt.mp4",
    pix_fmt: "yuv420p10le",
    overwrite: true,
  });
  assert.ok(cmd.startsWith("ffmpeg-util pixfmt"), "should start with ffmpeg-util pixfmt");
  assert.ok(cmd.includes("--pix-fmt"), "should include --pix-fmt flag");
  assert.ok(cmd.includes("yuv420p10le"), "should include the format value");
});
