import { useEffect, useRef, useState } from 'react';
import { useScreenCaptureContext } from '@/context/screen-capture-context';
import { wsService } from '@/services/websocket-service';
import { screenCaptureSession, screenChanged } from '@/utils/screen-vision';

const SAMPLE_MS = 5000;
const COMMENT_INTERVAL_MS = 45000;

export function useScreenCompanion(available: boolean) {
  const capture = useScreenCaptureContext();
  const captureRef = useRef(capture);
  captureRef.current = capture;
  const [enabled, setEnabled] = useState(false);
  const active = enabled && available && capture.isStreaming;
  const lastComment = useRef(-Infinity);
  const baseline = useRef<{ token: string; pixels: Uint8ClampedArray } | null>(null);

  useEffect(() => {
    if (!enabled || !capture.isStreaming) baseline.current = null;
  }, [enabled, capture.isStreaming]);

  useEffect(() => {
    let disposed = false;
    let sampling = false;
    const publish = (ready: boolean) => {
      if (wsService.getCurrentState() === 'OPEN') {
        wsService.sendMessage({ type: 'screen-companion-state', enabled: ready && screenCaptureSession.enabled,
          permission_token: screenCaptureSession.token });
      }
    };
    const sample = async () => {
      if (disposed || sampling || wsService.getCurrentState() !== 'OPEN') return;
      const token = screenCaptureSession.token;
      const current = () => !disposed && screenCaptureSession.isCurrent(token) && wsService.getCurrentState() === 'OPEN';
      if (!current()) return;
      sampling = true;
      try {
        const pixels = await captureRef.current.sampleScreen();
        if (!pixels || !current()) return;
        const previous = baseline.current;
        if (!previous || previous.token !== token) {
          baseline.current = { token, pixels };
          return;
        }
        if (performance.now() - lastComment.current < COMMENT_INTERVAL_MS || !screenChanged(previous.pixels, pixels)) return;
        const frame = await captureRef.current.captureScreen();
        if (!frame || !current()) return;
        baseline.current = { token, pixels };
        lastComment.current = performance.now();
        wsService.sendMessage({ type: 'screen-companion-frame', images: [frame] });
      } finally { sampling = false; }
    };
    if (!active) return undefined;
    const permission = screenCaptureSession.subscribe(() => queueMicrotask(() => { if (!disposed) publish(true); }));
    const connection = wsService.onStateChange(state => {
      if (state === 'OPEN') queueMicrotask(() => { if (!disposed) publish(true); });
      else baseline.current = null;
    });
    publish(true);
    void sample();
    const timer = window.setInterval(() => { void sample(); }, SAMPLE_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      permission();
      connection.unsubscribe();
      publish(false);
    };
  }, [active]);

  return { enabled, setEnabled };
}
