import { useEffect, useRef, useState } from 'react';

export type WorkArea = { x: number; y: number; width: number; height: number };
type ModelBounds = { left: number; right: number; top: number; bottom: number };

function getModelBounds(meshCache: WeakMap<object, ModelBounds>): ModelBounds | null {
  const canvas = document.getElementById('canvas');
  const model = (window as any).getLAppAdapter?.()?.getModel?.();
  const mesh = model?.getModel?.();
  const matrix = model?.getRenderer?.()?.getMvpMatrix?.()?.getArray?.();
  if (!canvas || !mesh || !matrix || !matrix[0] || !matrix[5]) return null;
  const rect = canvas.getBoundingClientRect();
  let bounds = meshCache.get(mesh);
  if (!bounds) {
    // Capture a model-space envelope once. Pose animation changes vertices, not the placement transform.
    let left = Infinity, bottom = Infinity, right = -Infinity, top = -Infinity;
    for (let i = 0; i < mesh.getDrawableCount(); i++) {
      if (!mesh.getDrawableDynamicFlagIsVisible(i) || mesh.getDrawableOpacity(i) <= 0.01) continue;
      const vertices = mesh.getDrawableVertices(i);
      for (let j = 0; j < vertices.length; j += 2) {
        left = Math.min(left, vertices[j]); right = Math.max(right, vertices[j]);
        bottom = Math.min(bottom, vertices[j + 1]); top = Math.max(top, vertices[j + 1]);
      }
    }
    if (!Number.isFinite(left + right + top + bottom)) return null;
    bounds = { left, right, top, bottom };
    meshCache.set(mesh, bounds);
  }
  const xs: number[] = [], ys: number[] = [];
  for (const x of [bounds.left, bounds.right]) {
    for (const y of [bounds.top, bounds.bottom]) {
      xs.push(rect.left + rect.width * (1 + matrix[0] * x + matrix[4] * y + matrix[12]) / 2);
      ys.push(rect.top + rect.height * (1 - matrix[1] * x - matrix[5] * y - matrix[13]) / 2);
    }
  }
  return { left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys) };
}

const clamp = (n: number, low: number, high: number) => Math.max(low, Math.min(high, n));

export function dockPlacement(model: ModelBounds | null, workAreas: WorkArea[], viewport: WorkArea) {
  const bounds = model || { left: viewport.width / 2, right: viewport.width / 2,
    top: viewport.height - 120, bottom: viewport.height - 120 };
  const centerX = (bounds.left + bounds.right) / 2;
  const centerY = (bounds.top + bounds.bottom) / 2;
  const distance = (a: WorkArea) => Math.hypot(centerX - clamp(centerX, a.x, a.x + a.width),
    centerY - clamp(centerY, a.y, a.y + a.height));
  const area = workAreas.reduce<WorkArea | undefined>((closest, current) => (
    !closest || distance(current) < distance(closest) ? current : closest), undefined) || viewport;
  const gap = 8;
  const leftEdge = area.x + gap, rightEdge = area.x + area.width - gap;
  const top = area.y + gap, bottom = area.y + area.height - gap;
  const preferredWidth = Math.min(304, rightEdge - leftEdge);
  const centeredLeft = centerX - preferredWidth / 2;
  const above = clamp(bounds.top - gap, top, bottom);
  const below = clamp(bounds.bottom + gap, top, bottom);
  const spaceAbove = above - top, spaceBelow = bottom - below;
  const rightOfPet = clamp(bounds.right + gap, leftEdge, rightEdge);
  const leftOfPet = clamp(bounds.left - gap, leftEdge, rightEdge);
  const roomRight = rightEdge - rightOfPet, roomLeft = leftOfPet - leftEdge;

  // Anchor speech near the face with an independent layout, so talking never moves the controls.
  const speechGap = 14;
  const speechRight = bounds.right + speechGap;
  const speechLeft = bounds.left - speechGap;
  const canSpeakRight = rightEdge - speechRight >= Math.min(150, preferredWidth);
  const canSpeakLeft = speechLeft - leftEdge >= Math.min(150, preferredWidth);
  const speechSide = canSpeakRight ? 'right' : canSpeakLeft ? 'left' : spaceAbove >= spaceBelow ? 'above' : 'below';
  const beside = speechSide === 'right' || speechSide === 'left';
  const speechWidth = Math.min(278, speechSide === 'right' ? rightEdge - speechRight
    : speechSide === 'left' ? speechLeft - leftEdge : preferredWidth);
  const speechMaxHeight = beside ? Math.min(155, bottom - top)
    : Math.min(155, speechSide === 'above' ? spaceAbove : spaceBelow);
  const speechTop = beside ? clamp(bounds.top + (bounds.bottom - bounds.top) * .26 - 18, top, bottom - speechMaxHeight)
    : speechSide === 'above' ? above : below;
  const speechX = speechSide === 'right' ? speechRight : speechSide === 'left' ? speechLeft
    : clamp(centerX, leftEdge + speechWidth / 2, rightEdge - speechWidth / 2);
  const speech = { side: speechSide, left: Math.round(speechX), top: Math.round(speechTop),
    maxWidth: Math.floor(speechWidth), maxHeight: Math.floor(speechMaxHeight) };

  let width = preferredWidth;
  let left = clamp(centeredLeft, leftEdge, rightEdge - width);
  let align: 'left' | 'center' | 'right' = 'center';
  let up = spaceBelow < 220 && spaceAbove > spaceBelow;
  let anchor = up ? above : below;
  const overLeft = Math.min(centeredLeft, bounds.left) < leftEdge;
  const overRight = Math.max(centeredLeft + width, bounds.right) > rightEdge;
  if (overLeft || overRight || Math.max(spaceAbove, spaceBelow) < 145) {
    const onRight = overLeft === overRight ? roomRight >= roomLeft : overLeft;
    const sideRoom = onRight ? roomRight : roomLeft;
    if (sideRoom >= Math.min(208, preferredWidth)) {
      width = Math.min(preferredWidth, sideRoom);
      left = onRight ? rightOfPet : leftOfPet - width;
      align = onRight ? 'left' : 'right';
      const middle = clamp(centerY, top, bottom);
      up = bottom - middle < 220 && middle - top > bottom - middle;
      anchor = middle;
    }
  }
  return { left: Math.round(left), width: Math.floor(width), up, align, anchor: Math.round(anchor),
    maxHeight: Math.floor(up ? anchor - top : bottom - anchor), speech };
}

const viewport = () => ({ x: 0, y: 0, width: window.innerWidth, height: window.innerHeight });

export function usePetDock() {
  const [placement, setPlacement] = useState(() => dockPlacement(null, [], viewport()));
  const [modelHover, setModelHover] = useState(false);
  const meshCache = useRef(new WeakMap<object, ModelBounds>());
  useEffect(() => {
    const ipc = window.electron?.ipcRenderer;
    let areas: WorkArea[] = [], disposed = false;
    const onHover = (_event: unknown, active: boolean) => setModelHover(active);
    ipc?.on('pet-model-hover', onHover);
    const reposition = () => {
      const next = dockPlacement(getModelBounds(meshCache.current), areas, viewport());
      setPlacement(previous => previous.up === next.up && previous.width === next.width
        && previous.anchor === next.anchor && previous.left === next.left
        && previous.align === next.align && previous.maxHeight === next.maxHeight
        && previous.speech.side === next.speech.side && previous.speech.left === next.speech.left
        && previous.speech.top === next.speech.top && previous.speech.maxWidth === next.speech.maxWidth
        && previous.speech.maxHeight === next.speech.maxHeight ? previous : next);
    };
    const resize = () => {
      void ipc?.invoke('pet-work-areas').then((result: WorkArea[]) => {
        if (!disposed) { areas = result; reposition(); }
      }).catch(() => {});
      reposition();
    };
    window.addEventListener('resize', resize);
    ipc?.on('pet-work-areas-changed', resize);
    resize();
    const timer = window.setInterval(reposition, 40);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener('resize', resize);
      ipc?.removeListener('pet-work-areas-changed', resize);
      ipc?.removeListener('pet-model-hover', onHover);
    };
  }, []);
  return { placement, modelHover };
}
