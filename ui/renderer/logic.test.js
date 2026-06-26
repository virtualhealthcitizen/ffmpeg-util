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
  assert.equal(L.inputTargetForTab("nope"), null);
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

test("dropUpdate returns null for empty paths or unknown tab", () => {
  assert.equal(L.dropUpdate([], "convert"), null);
  assert.equal(L.dropUpdate(["a.mp4"], "bogus"), null);
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
