/* eslint-disable no-shadow */
import { app, ipcMain, globalShortcut, desktopCapturer, screen } from "electron";
import { request } from 'node:http';
import { electronApp, optimizer } from "@electron-toolkit/utils";
import { WindowManager } from "./window-manager";
import { MenuManager } from "./menu-manager";

let windowManager: WindowManager;
let menuManager: MenuManager;
let isQuitting = false;

function setupIPC(): void {
  ipcMain.handle("get-platform", () => process.platform);

  ipcMain.on("set-ignore-mouse-events", (_event, ignore: boolean) => {
    const window = windowManager.getWindow();
    if (window) {
      windowManager.setIgnoreMouseEvents(ignore);
    }
  });

  ipcMain.on("get-current-mode", (event) => {
    event.returnValue = windowManager.getCurrentMode();
  });

  ipcMain.on("pre-mode-changed", (_event, newMode) => {
    if (newMode === 'window' || newMode === 'pet') {
      menuManager.setMode(newMode);
    }
  });

  ipcMain.on("window-minimize", () => {
    windowManager.getWindow()?.minimize();
  });

  ipcMain.on("window-maximize", () => {
    const window = windowManager.getWindow();
    if (window) {
      windowManager.maximizeWindow();
    }
  });

  ipcMain.on("window-close", () => {
    const window = windowManager.getWindow();
    if (window) {
      if (process.platform === "darwin") {
        window.hide();
      } else {
        window.close();
      }
    }
  });

  ipcMain.on(
    "update-component-hover",
    (event, componentId: string, isHovering: boolean) => {
      const window = windowManager.getWindow();
      if (!window || event.sender !== window.webContents) return;
      windowManager.updateComponentHover(componentId, isHovering);
      if (componentId === 'live2d-model') window.webContents.send('pet-model-hover', isHovering);
    },
  );

  ipcMain.on('pet-keyboard-focus', (event, focused: boolean) => {
    if (event.sender === windowManager.getWindow()?.webContents) {
      windowManager.setPetKeyboardFocus(focused === true);
    }
  });

  ipcMain.handle("get-config-files", () => {
    const configFiles = JSON.parse(localStorage.getItem("configFiles") || "[]");
    menuManager.updateConfigFiles(configFiles);
    return configFiles;
  });

  ipcMain.on("update-config-files", (_event, files) => {
    menuManager.updateConfigFiles(files);
  });

  ipcMain.handle('list-screen-sources', async () => {
    const sources = await desktopCapturer.getSources({
      types: ['screen', 'window'], thumbnailSize: { width: 0, height: 0 }, fetchWindowIcons: false,
    });
    const displays = screen.getAllDisplays();
    const primaryId = String(screen.getPrimaryDisplay().id);
    const ownWindow = windowManager.getWindow()?.getMediaSourceId();
    return sources.filter((source) => source.id !== ownWindow).map((source) => {
      const display = displays.find((item) => String(item.id) === source.display_id);
      return {
        id: source.id, name: source.name, kind: source.id.startsWith('screen:') ? 'screen' : 'window',
        primary: source.display_id === primaryId,
        width: display ? Math.round(display.size.width * display.scaleFactor) : undefined,
        height: display ? Math.round(display.size.height * display.scaleFactor) : undefined,
      };
    });
  });

  ipcMain.handle('pet-work-areas', (event) => {
    const window = windowManager.getWindow();
    if (!window || event.sender !== window.webContents) return [];
    const bounds = window.getContentBounds();
    return screen.getAllDisplays().map(({ workArea }) => ({
      ...workArea, x: workArea.x - bounds.x, y: workArea.y - bounds.y,
    }));
  });

  ipcMain.handle('pet-tavern-controls', (event, base: string, action: 'state' | 'command', payload = {}) => {
    const window = windowManager.getWindow();
    if (!window || event.sender !== window.webContents || !event.senderFrame?.url.startsWith('file:')) {
      throw new Error('此操作仅供桌宠客户端使用。');
    }
    const url = new URL(base);
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
        || url.username || url.password || (action !== 'state' && action !== 'command')) {
      throw new Error('请使用本机桌宠地址。');
    }
    const data = JSON.stringify(payload);
    return new Promise((resolve, reject) => {
      const req = request(new URL('/api/game/sillytavern/desktop-' + action, url), {
        method: 'POST', headers: { Origin: 'dafeiyu://desktop', 'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data) },
      }, (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (part) => {
          body += part;
          if (body.length > 65536) req.destroy(new Error('酒馆状态过长。'));
        });
        res.on('error', reject);
        res.on('end', () => {
          try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
        });
      });
      req.setTimeout(2000, () => req.destroy(new Error('桌宠服务连接超时。')));
      req.on('error', reject);
      req.end(data);
    });
  });
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId("com.electron");

  windowManager = new WindowManager();
  menuManager = new MenuManager((mode) => windowManager.setWindowMode(mode));

  const window = windowManager.createWindow({
    titleBarOverlay: {
      color: "#111111",
      symbolColor: "#FFFFFF",
      height: 30,
    },
  });
  const updateWorkAreas = () => { if (!window.isDestroyed()) window.webContents.send('pet-work-areas-changed'); };
  screen.on('display-metrics-changed', updateWorkAreas);
  screen.on('display-added', updateWorkAreas);
  screen.on('display-removed', updateWorkAreas);
  window.once('closed', () => {
    screen.removeListener('display-metrics-changed', updateWorkAreas);
    screen.removeListener('display-added', updateWorkAreas);
    screen.removeListener('display-removed', updateWorkAreas);
  });
  menuManager.createTray();

  window.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      window.hide();
    }
    return false;
  });

  // if (process.env.NODE_ENV === "development") {
  //   globalShortcut.register("F12", () => {
  //     const window = windowManager.getWindow();
  //     if (!window) return;

  //     if (window.webContents.isDevToolsOpened()) {
  //       window.webContents.closeDevTools();
  //     } else {
  //       window.webContents.openDevTools();
  //     }
  //   });
  // }

  setupIPC();

  app.on("activate", () => {
    const window = windowManager.getWindow();
    if (window) {
      window.show();
    }
  });

  app.on("browser-window-created", (_, window) => {
    optimizer.watchWindowShortcuts(window);
  });

  app.on('web-contents-created', (_, contents) => {
    contents.session.setPermissionRequestHandler((webContents, permission, callback) => {
      if (permission === 'media') {
        callback(true);
      } else {
        callback(false);
      }
    });
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  menuManager.destroy();
  globalShortcut.unregisterAll();
});
