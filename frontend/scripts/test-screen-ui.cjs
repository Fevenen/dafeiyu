const { app, BrowserWindow } = require("electron");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const output = path.resolve(__dirname, "../../../tools/vision-ui-build");
app.setPath("userData", path.join(output, "test-profile"));
app.commandLine.appendSwitch("disable-gpu-shader-disk-cache");
app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: 900,
    height: 800,
    show: false,
    webPreferences: { contextIsolation: true, backgroundThrottling: false },
  });
  const run = (code) => window.webContents.executeJavaScript(code);
  const wait = async (condition) => {
    for (let n = 0; n < 100; n += 1) {
      if (await run(condition)) return;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error("Timed out: " + condition);
  };
  try {
    await window.loadFile(path.join(output, "vision-fixture.html"));
    await wait("!!window.vision");
    await run('window.connectScreenTestSocket()');
    await wait('window.socketMessages.some(m => m.type === "screen-vision-state" && !m.enabled)');
    await run('window.requestScreenTestFrame("closed-request", "invalid")');
    await wait('window.socketMessages.some(m => m.request_id === "closed-request")');
    assert.equal(await run('window.socketMessages.find(m => m.request_id === "closed-request").images.length'), 0);
    assert.equal(await run("window.requests"), 0);
    assert.equal(await run("window.vision.isStreaming"), false);
    await run(`document.querySelector('[aria-label="开启屏幕视觉"]').click()`);
    await wait("!!window.vision.lastFrame");
    await wait('window.socketMessages.some(m => m.type === "screen-vision-state" && m.enabled)');
    await run('window.screenGrant = window.socketMessages.filter(m => m.type === "screen-vision-state" && m.enabled).at(-1).permission_token; window.requestScreenTestFrame("open-request", window.screenGrant)');
    await wait('window.socketMessages.some(m => m.request_id === "open-request")');
    assert.equal(await run('window.socketMessages.find(m => m.request_id === "open-request").images.length'), 1);
    assert.deepEqual(
      await run(
        "[window.vision.lastFrame.metadata.original_width, window.vision.lastFrame.metadata.original_height, window.vision.lastFrame.metadata.width, window.vision.lastFrame.metadata.height]",
      ),
      [3840, 2160, 1600, 900],
    );
    await run(`(() => {
      const image=document.querySelector('img'); const rect=image.getBoundingClientRect(); image.setPointerCapture=()=>{};
      image.dispatchEvent(new PointerEvent('pointerdown',{pointerId:1,button:0,bubbles:true,clientX:rect.left+rect.width*.25,clientY:rect.top+rect.height*.25}));
    })()`);
    await new Promise((resolve) => setTimeout(resolve, 100));
    await run(`(() => {
      const image=document.querySelector('img'); const rect=image.getBoundingClientRect();
      image.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,button:0,bubbles:true,clientX:rect.left+rect.width*.75,clientY:rect.top+rect.height*.75}));
    })()`);
    await run("window.vision.captureScreen()");
    await wait("!!window.vision.lastFrame?.metadata.crop");
    const pixel = await run(`(async () => {
      const image = new Image(); image.src = window.vision.lastFrame.data; await image.decode();
      const canvas = document.createElement('canvas'); canvas.width=1; canvas.height=1;
      const ctx = canvas.getContext('2d'); ctx.drawImage(image,0,0); return Array.from(ctx.getImageData(0,0,1,1).data);
    })()`);
    assert.deepEqual(pixel.slice(0, 3), [16, 185, 129]);
    fs.writeFileSync(
      path.join(output, "synthetic-frame.json"),
      JSON.stringify(await run("window.vision.lastFrame")),
    );
    await new Promise((resolve) => setTimeout(resolve, 500));
    fs.writeFileSync(
      path.join(output, "controls-preview.png"),
      (await window.webContents.capturePage()).toPNG(),
    );
    await run(`document.querySelector('[aria-label="关闭屏幕视觉"]').click()`);
    await wait(
      "!window.vision.isStreaming && !window.vision.preview && !window.vision.lastFrame",
    );
    assert.equal(
      await run(
        'window.mockStreams.every(s => s.getTracks().every(t => t.readyState === "ended"))',
      ),
      true,
    );
    assert.equal(await run("window.vision.captureScreen()"), null);
    await run('window.requestScreenTestFrame("revoked-request", window.screenGrant)');
    await wait('window.socketMessages.some(m => m.request_id === "revoked-request")');
    assert.equal(await run('window.socketMessages.find(m => m.request_id === "revoked-request").images.length'), 0);
    await run(
      `window.slowAcquire=true; document.querySelector('[aria-label="开启屏幕视觉"]').click()`,
    );
    await wait("window.vision.isStarting && !!window.finishAcquire");
    await run(
      `document.querySelector('[aria-label="关闭屏幕视觉"]').click(); window.finishAcquire()`,
    );
    await wait(
      'window.mockStreams.every(s => s.getTracks().every(t => t.readyState === "ended"))',
    );
    assert.equal(await run("window.vision.isStreaming"), false);
    const loaded = new Promise((resolve) =>
      window.webContents.once("did-finish-load", resolve),
    );
    window.reload();
    await loaded;
    await wait("!!window.vision");
    assert.equal(await run("window.requests"), 0);
    assert.equal(await run("window.vision.isStreaming"), false);
    console.log(
      "PASS: default off, native 4K detail, real canvas crop/PNG decode, preview, stop, pending acquisition cancellation, restart defaults",
    );
    app.exit(0);
  } catch (error) {
    console.error(error);
    console.error(
      await run("document.body.innerText").catch(() => "renderer unavailable"),
    );
    app.exit(1);
  }
});
