/** Session-only screen permission; deliberately never persisted. */
export class ScreenCaptureSession {
  private revision = 0;
  private readonly sessionId =
    globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  private currentStream: MediaStream | null = null;
  private listeners = new Set<() => void>();
  requested = false;
  get stream() {
    return this.currentStream;
  }
  get token() {
    return `${this.sessionId}:${this.revision}`;
  }
  get enabled() {
    return (
      this.requested &&
      !!this.currentStream
        ?.getVideoTracks()
        .some((track) => track.readyState === "live")
    );
  }
  isCurrent(token: string) {
    return this.enabled && token === this.token;
  }
  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  private notify() {
    this.listeners.forEach((listener) => listener());
  }
  stop() {
    this.revision += 1;
    this.requested = false;
    const stream = this.currentStream;
    this.currentStream = null;
    stream?.getTracks().forEach((track) => track.stop());
    this.notify();
  }
  invalidate() {
    this.revision += 1;
    this.notify();
  }
  async start(acquire: (stillWanted: () => boolean) => Promise<MediaStream>) {
    this.stop();
    this.requested = true;
    const token = this.token;
    this.notify();
    try {
      const stream = await acquire(
        () => this.requested && token === this.token,
      );
      if (!this.requested || token !== this.token) {
        stream.getTracks().forEach((track) => track.stop());
        return null;
      }
      this.currentStream = stream;
      stream.getVideoTracks().forEach((track) => {
        track.addEventListener(
          "ended",
          () => {
            if (this.currentStream === stream) this.stop();
          },
          { once: true },
        );
      });
      this.notify();
      return stream;
    } catch (error) {
      if (token !== this.token || !this.requested) return null;
      this.stop();
      throw error;
    }
  }
}
export interface CropRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}
export function clampCrop(crop: CropRegion | null): CropRegion | null {
  if (!crop || !Object.values(crop).every(Number.isFinite)) return null;
  const x = Math.min(1, Math.max(0, crop.x));
  const y = Math.min(1, Math.max(0, crop.y));
  const width = Math.min(1 - x, Math.max(0, crop.width));
  const height = Math.min(1 - y, Math.max(0, crop.height));
  return width >= 0.02 && height >= 0.02 ? { x, y, width, height } : null;
}
export function fitImageSize(width: number, height: number, maxEdge: number) {
  if (
    ![width, height, maxEdge].every(
      (value) => Number.isFinite(value) && value > 0,
    )
  )
    throw new Error("Invalid screen image size");
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}
export const screenCaptureSession = new ScreenCaptureSession();
/** Last synchronous gate, including frames captured before a stop/source switch. */
export function authorizeScreenImages<T extends object>(
  message: T,
  session = screenCaptureSession,
): T {
  const payload = message as T & {
    images?: { source?: string; metadata?: { permission_token?: string } }[];
  };
  if (!Array.isArray(payload.images)) return message;
  return {
    ...payload,
    images: payload.images.filter(
      (image) =>
        image.source !== "screen" ||
        session.isCurrent(image.metadata?.permission_token || ""),
    ),
  };
}
