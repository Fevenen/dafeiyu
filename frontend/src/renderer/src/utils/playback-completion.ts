/** One completion owner; repeated/late markers never stop another audio segment. */
export class PlaybackCompletion {
  private seen = new Set<string>();
  private drain: () => Promise<void>;
  private send: (message: object) => void;
  constructor(
    drain: () => Promise<void>,
    send: (message: object) => void,
  ) {
    this.drain = drain;
    this.send = send;
  }
  async complete(requestId?: string) {
    const key = requestId || 'legacy-pending';
    if (this.seen.has(key)) return;
    this.seen.add(key);
    try {
      await this.drain();
      this.send({ type: 'frontend-playback-complete', ...(requestId ? { request_id: requestId } : {}) });
    } catch (error) {
      this.seen.delete(key);
      throw error;
    } finally {
      if (!requestId) this.seen.delete(key);
      if (this.seen.size > 200) this.seen.delete(this.seen.values().next().value!);
    }
  }
}
