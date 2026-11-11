import assert from "node:assert/strict";
import test from "node:test";
import {
  ScreenCaptureSession,
  authorizeScreenImages,
  clampCrop,
  fitImageSize,
} from "../src/renderer/src/utils/screen-vision.ts";

function fakeStream() {
  const events = new EventTarget();
  const track = {
    readyState: "live",
    stop() {
      this.readyState = "ended";
    },
    addEventListener: events.addEventListener.bind(events),
  };
  return {
    getTracks: () => [track],
    getVideoTracks: () => [track],
    end: () => events.dispatchEvent(new Event("ended")),
  };
}
const frame = (session) => ({
  source: "screen",
  data: "test pixels",
  metadata: { permission_token: session.token },
});

test("default off: unsolicited screenshots are stripped but camera/text remain", () => {
  const session = new ScreenCaptureSession();
  const camera = { source: "camera", data: "camera" };
  const payload = { text: "hello", images: [frame(session), camera] };
  assert.equal(session.enabled, false);
  assert.deepEqual(authorizeScreenImages(payload, session), {
    text: "hello",
    images: [camera],
  });
  assert.equal(payload.images.length, 2);
});
test("stop during acquisition releases a late stream and never enables the screen", async () => {
  const session = new ScreenCaptureSession();
  let resolve;
  const stream = fakeStream();
  const start = session.start(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  session.stop();
  resolve(stream);
  assert.equal(await start, null);
  assert.equal(stream.getTracks()[0].readyState, "ended");
  assert.equal(session.enabled, false);
});
test("a previous acquisition cannot replace a newer session", async () => {
  const session = new ScreenCaptureSession();
  let resolve;
  const old = fakeStream();
  const current = fakeStream();
  const first = session.start(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  await session.start(async () => current);
  resolve(old);
  await first;
  assert.equal(session.stream, current);
  assert.equal(old.getTracks()[0].readyState, "ended");
  session.stop();
});
test("stop/source/crop changes revoke already captured frames at send time", async () => {
  const session = new ScreenCaptureSession();
  await session.start(async () => fakeStream());
  const before = frame(session);
  assert.equal(
    authorizeScreenImages({ images: [before] }, session).images.length,
    1,
  );
  session.invalidate();
  assert.equal(
    authorizeScreenImages({ images: [before] }, session).images.length,
    0,
  );
  const after = frame(session);
  session.stop();
  assert.equal(
    authorizeScreenImages({ images: [after] }, session).images.length,
    0,
  );
});
test("OS sharing-ended event closes the permission lease", async () => {
  const session = new ScreenCaptureSession();
  const stream = fakeStream();
  await session.start(async () => stream);
  stream.end();
  assert.equal(session.enabled, false);
});
test("image scaling preserves aspect ratio, portrait screens, and native crop detail", () => {
  assert.deepEqual(fitImageSize(3840, 2160, 1600), {
    width: 1600,
    height: 900,
  });
  assert.deepEqual(fitImageSize(1440, 2560, 1600), {
    width: 900,
    height: 1600,
  });
  assert.deepEqual(fitImageSize(500, 300, 1600), { width: 500, height: 300 });
  assert.throws(() => fitImageSize(0, 500, 1600));
});
test("crop selection rejects tiny/invalid rectangles and stays inside source bounds", () => {
  assert.equal(clampCrop({ x: 0, y: 0, width: 0.001, height: 0.5 }), null);
  assert.equal(clampCrop({ x: NaN, y: 0, width: 0.5, height: 0.5 }), null);
  assert.deepEqual(clampCrop({ x: 0.5, y: 0.5, width: 0.8, height: 0.8 }), {
    x: 0.5,
    y: 0.5,
    width: 0.5,
    height: 0.5,
  });
});
