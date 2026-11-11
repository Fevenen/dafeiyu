import {
  createContext,
  useContext,
  useState,
  useRef,
  useEffect,
  ReactNode,
} from "react";
import { toaster } from "@/components/ui/toaster";
import { wsService } from "@/services/websocket-service";
import {
  clampCrop,
  CropRegion,
  fitImageSize,
  screenCaptureSession as session,
} from "@/utils/screen-vision";

export interface ScreenSource {
  id: string;
  name: string;
  kind: "screen" | "window";
  width?: number;
  height?: number;
  primary?: boolean;
}
export interface ScreenFrame {
  source: "screen";
  data: string;
  mime_type: string;
  metadata: {
    permission_token: string;
    frame_id: string;
    captured_at: string;
    source_name: string;
    source_id: string;
    source_kind: string;
    original_width: number;
    original_height: number;
    width: number;
    height: number;
    capture_ms: number;
    crop: CropRegion | null;
  };
}
interface CaptureSettings {
  maxEdge: number;
  format: "image/png" | "image/jpeg";
}
interface ScreenCaptureContextType {
  stream: MediaStream | null;
  isStreaming: boolean;
  isStarting: boolean;
  error: string;
  sources: ScreenSource[];
  selectedSource: string;
  sourceName: string;
  settings: CaptureSettings;
  crop: CropRegion | null;
  lastFrame: ScreenFrame | null;
  preview: string | null;
  startCapture: () => Promise<void>;
  stopCapture: () => void;
  loadSources: () => Promise<void>;
  selectSource: (id: string) => void;
  updateSettings: (value: Partial<CaptureSettings>) => void;
  setCrop: (value: CropRegion | null) => void;
  captureScreen: () => Promise<ScreenFrame | null>;
}
const ScreenCaptureContext = createContext<
  ScreenCaptureContextType | undefined
>(undefined);

export function ScreenCaptureProvider({ children }: { children: ReactNode }) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState("");
  const [sources, setSources] = useState<ScreenSource[]>([]);
  const [selectedSource, setSelectedSource] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [settings, setSettings] = useState<CaptureSettings>({
    maxEdge: 1600,
    format: "image/png",
  });
  const [crop, updateCrop] = useState<CropRegion | null>(null);
  const [lastFrame, setLastFrame] = useState<ScreenFrame | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const sourceRef = useRef<ScreenSource | null>(null);
  const settingsRef = useRef(settings);
  const cropRef = useRef<CropRegion | null>(null);
  const pending = useRef<{
    token: string;
    promise: Promise<ScreenFrame | null>;
  } | null>(null);

  const clearFrame = () => {
    setLastFrame(null);
    setPreview(null);
  };
  useEffect(() => {
    const unsubscribe = session.subscribe(() => {
      setStream(session.stream);
      setIsStarting(session.requested && !session.stream);
      if (!session.enabled) clearFrame();
    });
    return () => {
      unsubscribe();
      session.stop();
    };
  }, []);

  const readSources = async (): Promise<ScreenSource[]> => {
    if (!window.electron) return [];
    return window.electron.ipcRenderer.invoke("list-screen-sources");
  };
  const loadSources = async () => {
    try {
      setSources(await readSources());
      setError("");
    } catch {
      setError("无法读取屏幕列表，请重试。");
    }
  };
  const stopCapture = () => {
    session.stop();
    setError("");
  };
  const selectSource = (id: string) => {
    stopCapture();
    setSelectedSource(id);
    cropRef.current = null;
    updateCrop(null);
  };
  const setCrop = (value: CropRegion | null) => {
    cropRef.current = clampCrop(value);
    updateCrop(cropRef.current);
    session.invalidate();
    setLastFrame(null);
  };
  const updateSettings = (value: Partial<CaptureSettings>) => {
    const next = { ...settingsRef.current, ...value };
    next.maxEdge = Math.max(640, Math.min(2560, next.maxEdge));
    settingsRef.current = next;
    setSettings(next);
    session.invalidate();
    setLastFrame(null);
  };

  const captureScreen = async (): Promise<ScreenFrame | null> => {
    if (!session.enabled) return null;
    const token = session.token;
    if (pending.current?.token === token) return pending.current.promise;
    const promise = (async () => {
      let bitmap: ImageBitmap | undefined;
      const started = performance.now();
      try {
        const track = session.stream?.getVideoTracks()[0];
        if (!track || track.readyState !== "live") return null;
        bitmap = await new (window as any).ImageCapture(track).grabFrame();
        if (!session.isCurrent(token)) return null;
        const capturedAt = new Date().toISOString();
        const region = cropRef.current;
        const { maxEdge, format } = settingsRef.current;
        const sx = Math.floor((region?.x || 0) * bitmap!.width);
        const sy = Math.floor((region?.y || 0) * bitmap!.height);
        const sw = Math.max(
          1,
          Math.floor((region?.width || 1) * bitmap!.width),
        );
        const sh = Math.max(
          1,
          Math.floor((region?.height || 1) * bitmap!.height),
        );
        const size = fitImageSize(sw, sh, maxEdge);
        const canvas = document.createElement("canvas");
        canvas.width = size.width;
        canvas.height = size.height;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas unavailable");
        ctx.drawImage(bitmap!, sx, sy, sw, sh, 0, 0, size.width, size.height);
        const data = canvas.toDataURL(format, 0.85);
        const thumbnailSize = fitImageSize(bitmap!.width, bitmap!.height, 960);
        canvas.width = thumbnailSize.width;
        canvas.height = thumbnailSize.height;
        ctx.drawImage(bitmap!, 0, 0, thumbnailSize.width, thumbnailSize.height);
        const thumbnail = canvas.toDataURL("image/jpeg", 0.8);
        if (!session.isCurrent(token)) return null;
        const source = sourceRef.current;
        const frame: ScreenFrame = {
          source: "screen",
          data,
          mime_type: format,
          metadata: {
            permission_token: token,
            frame_id: crypto.randomUUID(),
            captured_at: capturedAt,
            source_name: source?.name || track.label || "屏幕共享",
            source_id: source?.id || track.id,
            source_kind: source?.kind || "screen",
            original_width: bitmap!.width,
            original_height: bitmap!.height,
            width: size.width,
            height: size.height,
            capture_ms: Math.round(performance.now() - started),
            crop: region,
          },
        };
        setLastFrame(frame);
        setPreview(thumbnail);
        setError("");
        return frame;
      } catch {
        if (session.isCurrent(token)) {
          setError("这次截图失败，请刷新预览或重新开启屏幕。");
          toaster.create({
            title: "截图失败，本次只发送文字或语音",
            type: "error",
            duration: 2500,
          });
        }
        return null;
      } finally {
        bitmap?.close();
      }
    })();
    pending.current = { token, promise };
    try {
      return await promise;
    } finally {
      if (pending.current?.promise === promise) pending.current = null;
    }
  };

  const captureRef = useRef(captureScreen);
  captureRef.current = captureScreen;
  useEffect(() => {
    const publishPermission = () => {
      if (wsService.getCurrentState() === "OPEN") {
        wsService.sendMessage({
          type: "screen-vision-state",
          enabled: session.enabled,
          permission_token: session.token,
        });
      }
    };
    const permissionSubscription = session.subscribe(publishPermission);
    const connectionSubscription = wsService.onStateChange((state) => {
      if (state === "OPEN") publishPermission();
    });
    const requestSubscription = wsService.onMessage((message) => {
      if (message.type !== "screen-capture-request" || !message.request_id)
        return;
      const token = message.permission_token || "";
      void (async () => {
        const frame = session.isCurrent(token)
          ? await captureRef.current()
          : null;
        wsService.sendMessage({
          type: "screen-capture-result",
          request_id: message.request_id,
          images: frame && session.isCurrent(token) ? [frame] : [],
        });
      })();
    });
    publishPermission();
    return () => {
      permissionSubscription();
      connectionSubscription.unsubscribe();
      requestSubscription.unsubscribe();
    };
  }, []);

  const startCapture = async () => {
    setError("");
    try {
      const acquired = await session.start(async (stillWanted) => {
        if (window.electron) {
          const available = await readSources();
          if (!stillWanted()) throw new DOMException("Stopped", "AbortError");
          setSources(available);
          const target = selectedSource
            ? available.find((source) => source.id === selectedSource)
            : available.find((source) => source.primary) ||
              available.find((source) => source.kind === "screen");
          if (!target) throw new Error("所选窗口已关闭，请重新选择。");
          sourceRef.current = target;
          setSourceName(target.name);
          setSelectedSource(target.id);
          const mandatory: Record<string, string | number> = {
            chromeMediaSource: "desktop",
            chromeMediaSourceId: target.id,
            maxWidth: target.width || 7680,
            maxHeight: target.height || 4320,
            maxFrameRate: 2,
          };
          if (target.width && target.height) {
            mandatory.minWidth = target.width;
            mandatory.minHeight = target.height;
          }
          return navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { mandatory } as MediaTrackConstraints,
          });
        }
        const acquiredStream = await navigator.mediaDevices.getDisplayMedia({
          audio: false,
          video: true,
        });
        sourceRef.current = null;
        setSourceName(
          acquiredStream.getVideoTracks()[0]?.label || "浏览器共享画面",
        );
        return acquiredStream;
      });
      if (acquired && session.enabled) await captureScreen();
    } catch (err) {
      const message = err instanceof Error ? err.message : "无法开始屏幕共享";
      setError(message);
      toaster.create({
        title: "屏幕未开启：" + message,
        type: "error",
        duration: 3500,
      });
    }
  };

  return (
    <ScreenCaptureContext.Provider
      value={{
        stream,
        isStreaming: !!stream && session.enabled,
        isStarting,
        error,
        sources,
        selectedSource,
        sourceName,
        settings,
        crop,
        lastFrame,
        preview,
        startCapture,
        stopCapture,
        loadSources,
        selectSource,
        updateSettings,
        setCrop,
        captureScreen,
      }}
    >
      {children}
    </ScreenCaptureContext.Provider>
  );
}
export function useScreenCaptureContext() {
  const context = useContext(ScreenCaptureContext);
  if (!context)
    throw new Error("useScreenCaptureContext requires ScreenCaptureProvider");
  return context;
}
