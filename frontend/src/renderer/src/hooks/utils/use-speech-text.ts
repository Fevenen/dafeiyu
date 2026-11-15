import { useSyncExternalStore } from 'react';
import { petDisplayText } from '@/utils/pet-display-text';

let speechText = '';
let hideTimer: number | undefined;
const listeners = new Set<() => void>();

export function setSpeechText(text: string) {
  window.clearTimeout(hideTimer);
  text = petDisplayText(text);
  if (speechText === text) return;
  speechText = text;
  for (const listener of listeners) listener();
}

export function showUnvoicedSpeech(text: string) {
  if (!petDisplayText(text)) return;
  setSpeechText(text);
  hideTimer = window.setTimeout(() => setSpeechText(''), speechReadingTime(speechText));
}

export function speechReadingTime(text: string) {
  return Math.min(14000, Math.max(5000, text.length * 110));
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useSpeechText() {
  return useSyncExternalStore(subscribe, () => speechText);
}
