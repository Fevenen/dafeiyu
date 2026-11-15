import {
  BrowserWindow, screen, shell, ipcMain, powerMonitor,
} from 'electron';
import { join } from 'path';
import { is } from '@electron-toolkit/utils';

const isMac = process.platform === 'darwin';

export class WindowManager {
  private window: BrowserWindow | null = null;

  private windowedBounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null = null;

  private hoveringComponents: Set<string> = new Set();

  private currentMode: 'window' | 'pet' = 'window';

  // Track if mouse events are forcibly ignored
  private forceIgnoreMouse = false;

  constructor() {
    ipcMain.on('renderer-ready-for-mode-change', (_event, newMode) => {
      if (newMode !== this.currentMode) return;
      setTimeout(() => {
        if (newMode !== this.currentMode) return;
        if (newMode === 'pet') {
          this.continueSetWindowModePet();
        } else {
          this.continueSetWindowModeWindow();
        }
      }, 500);
    });

    ipcMain.on('mode-change-rendered', () => {
      this.window?.setOpacity(1);
    });

    ipcMain.on('window-unfullscreen', () => {
      const window = this.getWindow();
      if (window && window.isFullScreen()) {
        window.setFullScreen(false);
      }
    });

    // Handle toggle force ignore mouse events from renderer
    ipcMain.on('toggle-force-ignore-mouse', () => {
      this.toggleForceIgnoreMouse();
    });
  }

  createWindow(options: Electron.BrowserWindowConstructorOptions): BrowserWindow {
    this.window = new BrowserWindow({
      width: 900,
      height: 670,
      show: false,
      transparent: true,
      backgroundColor: '#ffffff',
      autoHideMenuBar: true,
      frame: false,
      icon: process.platform === 'win32'
        ? join(__dirname, '../../resources/icon.ico')
        : join(__dirname, '../../resources/icon.png'),
      ...(isMac ? { titleBarStyle: 'hiddenInset' } : {}),
      webPreferences: {
        preload: join(__dirname, '../preload/index.js'),
        sandbox: false,
        contextIsolation: true,
        nodeIntegration: true,
      },
      hasShadow: false,
      paintWhenInitiallyHidden: true,
      ...options,
    });

    this.setupWindowEvents();
    this.loadContent();

    this.window.on('enter-full-screen', () => {
      this.window?.webContents.send('window-fullscreen-change', true);
    });

    this.window.on('leave-full-screen', () => {
      this.window?.webContents.send('window-fullscreen-change', false);
      this.raisePetWindow();
    });

    return this.window;
  }

  private setupWindowEvents(): void {
    if (!this.window) return;

    const raisePetWindow = () => this.raisePetWindow();
    this.window.on('show', raisePetWindow);
    this.window.on('restore', raisePetWindow);
    this.window.on('hide', () => {
      this.hoveringComponents.clear();
      this.applyPetMouseState();
      this.setPetKeyboardFocus(false);
    });
    this.window.on('blur', () => this.setPetKeyboardFocus(false));
    this.window.on('always-on-top-changed', (_event, onTop) => {
      if (!onTop) setImmediate(() => {
        const window = this.window;
        if (window && !window.isDestroyed() && window.isVisible() && !window.isAlwaysOnTop()) {
          this.raisePetWindow();
        }
      });
    });
    powerMonitor.on('resume', raisePetWindow);
    this.window.once('closed', () => {
      powerMonitor.removeListener('resume', raisePetWindow);
    });

    this.window.on('ready-to-show', () => {
      this.window?.show();
      this.window?.webContents.send(
        'window-maximized-change',
        this.window.isMaximized(),
      );
    });

    this.window.on('maximize', () => {
      this.window?.webContents.send('window-maximized-change', true);
    });

    this.window.on('unmaximize', () => {
      this.window?.webContents.send('window-maximized-change', false);
    });

    this.window.on('resize', () => {
      const window = this.getWindow();
      if (window) {
        const bounds = window.getBounds();
        const { width, height } = screen.getPrimaryDisplay().workArea;
        const isMaximized = bounds.width >= width && bounds.height >= height;
        window.webContents.send('window-maximized-change', isMaximized);
      }
    });

    this.window.webContents.setWindowOpenHandler((details) => {
      shell.openExternal(details.url);
      return { action: 'deny' };
    });
  }

  private loadContent(): void {
    if (!this.window) return;

    if (is.dev && process.env.ELECTRON_RENDERER_URL) {
      this.window.loadURL(process.env.ELECTRON_RENDERER_URL);
    } else {
      this.window.loadFile(join(__dirname, '../renderer/index.html'));
    }
  }

  setWindowMode(mode: 'window' | 'pet'): void {
    if (!this.window) return;

    if (mode === this.currentMode) {
      this.raisePetWindow();
      return;
    }
    this.currentMode = mode;
    this.hoveringComponents.clear();
    this.window.setOpacity(0);

    if (mode === 'window') {
      this.setWindowModeWindow();
    } else {
      this.setWindowModePet();
    }
  }

  private raisePetWindow(): void {
    const window = this.window;
    if (this.currentMode !== 'pet' || !window || window.isDestroyed()) return;
    window.setAlwaysOnTop(true, 'screen-saver');
    if (process.platform === 'win32' && window.isVisible() && !window.isMinimized()) {
      window.moveTop();
    }
  }

  private setWindowModeWindow(): void {
    if (!this.window) return;

    this.window.setAlwaysOnTop(false);
    this.window.setIgnoreMouseEvents(false);
    this.window.setResizable(true);
    this.window.setFocusable(true);
    this.window.setSkipTaskbar(false);
    this.window.setBackgroundColor('#ffffff');
    this.window.webContents.send('pre-mode-changed', 'window');
  }

  private continueSetWindowModeWindow(): void {
    if (!this.window) return;
    if (this.windowedBounds) {
      this.window.setBounds(this.windowedBounds);
    } else {
      this.window.setSize(900, 670);
      this.window.center();
    }

    if (isMac) {
      this.window.setWindowButtonVisibility(true);
      this.window.setVisibleOnAllWorkspaces(false, {
        visibleOnFullScreen: false,
      });
    }

    this.window?.setIgnoreMouseEvents(false, { forward: true });

    this.window.webContents.send('mode-changed', 'window');
  }

  private setWindowModePet(): void {
    if (!this.window) return;

    this.windowedBounds = this.window.getBounds();

    if (this.window.isFullScreen()) {
      this.window.setFullScreen(false);
    }

    this.window.setBackgroundColor('#00000000');

    this.raisePetWindow();
    this.window.setPosition(0, 0);

    this.window.webContents.send('pre-mode-changed', 'pet');
  }

  private continueSetWindowModePet(): void {
    if (!this.window) return;
    // Calculate the bounding rectangle that covers all connected displays.
    // This allows the transparent pet-mode window to span across monitors,
    // so the avatar can be dragged freely between them.
    const displays = screen.getAllDisplays();
    const minX = Math.min(...displays.map((d) => d.bounds.x));
    const minY = Math.min(...displays.map((d) => d.bounds.y));
    const maxX = Math.max(...displays.map((d) => d.bounds.x + d.bounds.width));
    const maxY = Math.max(...displays.map((d) => d.bounds.y + d.bounds.height));
    const combinedWidth = maxX - minX;
    const combinedHeight = maxY - minY;

    // Resize and position the window to cover the entire virtual screen
    // so the avatar is not clipped when dragged to a second monitor.
    this.window.setBounds({
      x: minX,
      y: minY,
      width: combinedWidth,
      height: combinedHeight,
    });

    if (isMac) this.window.setWindowButtonVisibility(false);
    this.window.setResizable(false);
    this.window.setFocusable(false);
    this.window.setSkipTaskbar(true);

    if (isMac) {
      this.window.setVisibleOnAllWorkspaces(true, {
        visibleOnFullScreen: true,
      });
    }
    this.applyPetMouseState();

    this.raisePetWindow();
    this.window.webContents.send('mode-changed', 'pet');
  }

  getWindow(): BrowserWindow | null {
    return this.window;
  }

  setIgnoreMouseEvents(ignore: boolean): void {
    if (!this.window) return;

    if (isMac) {
      this.window.setIgnoreMouseEvents(ignore);
      // this.window.setIgnoreMouseEvents(ignore, { forward: true });
    } else {
      this.window.setIgnoreMouseEvents(ignore, { forward: true });
    }
  }

  maximizeWindow(): void {
    if (!this.window) return;

    if (this.isWindowMaximized()) {
      if (this.windowedBounds) {
        this.window.setBounds(this.windowedBounds);
        this.windowedBounds = null;
        this.window.webContents.send('window-maximized-change', false);
      }
    } else {
      this.windowedBounds = this.window.getBounds();
      const { width, height } = screen.getPrimaryDisplay().workArea;
      this.window.setBounds({
        x: 0, y: 0, width, height,
      });
      this.window.webContents.send('window-maximized-change', true);
    }
  }

  isWindowMaximized(): boolean {
    if (!this.window) return false;
    const bounds = this.window.getBounds();
    const { width, height } = screen.getPrimaryDisplay().workArea;
    return bounds.width >= width && bounds.height >= height;
  }

  updateComponentHover(componentId: string, isHovering: boolean): void {
    if (this.currentMode === 'window') return;

    if (isHovering) {
      this.hoveringComponents.add(componentId);
    } else {
      this.hoveringComponents.delete(componentId);
    }

    this.applyPetMouseState();
  }

  private applyPetMouseState(): void {
    const window = this.window;
    if (this.currentMode !== 'pet' || !window || window.isDestroyed()) return;
    const shouldIgnore = this.forceIgnoreMouse || this.hoveringComponents.size === 0;
    this.setIgnoreMouseEvents(shouldIgnore);
  }

  setPetKeyboardFocus(focused: boolean): void {
    const window = this.window;
    if (this.currentMode !== 'pet' || !window || window.isDestroyed()) return;
    if (focused && (this.forceIgnoreMouse || !window.isVisible())) return;
    if (window.isFocusable() !== focused) {
      window.setFocusable(focused);
      // On Windows setFocusable also changes taskbar membership.
      window.setSkipTaskbar(true);
    }
    if (focused && !window.isFocused()) window.focus();
    if (!focused && window.isFocused()) window.blur();
  }

  // Toggle force ignore mouse events
  toggleForceIgnoreMouse(): void {
    this.forceIgnoreMouse = !this.forceIgnoreMouse;

    this.applyPetMouseState();
    if (this.forceIgnoreMouse) this.setPetKeyboardFocus(false);

    // Notify renderer about the change
    this.window?.webContents.send('force-ignore-mouse-changed', this.forceIgnoreMouse);
  }

  // Get current force ignore state
  isForceIgnoreMouse(): boolean {
    return this.forceIgnoreMouse;
  }

  // Get current mode
  getCurrentMode(): 'window' | 'pet' {
    return this.currentMode;
  }
}
