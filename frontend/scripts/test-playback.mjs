import test from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { TaskQueue } from '../src/renderer/src/utils/task-queue.ts';
import { PlaybackCompletion } from '../src/renderer/src/utils/playback-completion.ts';
import { audioManager } from '../src/renderer/src/utils/audio-manager.ts';

function gate() {
  let release;
  const promise = new Promise(resolve => { release = resolve; });
  return { promise, release };
}

test('one correlated acknowledgement waits for all audio, even with repeated markers', async () => {
  const audio = gate();
  const sent = [];
  const completion = new PlaybackCompletion(() => audio.promise, message => sent.push(message));
  const done = completion.complete('first');
  await completion.complete('first');
  assert.deepEqual(sent, []);
  audio.release();
  await done;
  await completion.complete('first');
  assert.deepEqual(sent, [{ type: 'frontend-playback-complete', request_id: 'first' }]);
});

test('a late marker for the previous utterance cannot finish the next audio', async () => {
  const queue = new TaskQueue(0);
  const sent = [];
  const completion = new PlaybackCompletion(() => queue.waitForCompletion(), message => sent.push(message));
  await completion.complete('old');
  const audio = gate();
  queue.addTask(() => audio.promise);
  const done = completion.complete('new');
  await completion.complete('old');
  await delay(20);
  assert.equal(queue.hasTask(), true);
  assert.equal(sent.length, 1);
  audio.release();
  await done;
  assert.deepEqual(sent.map(message => message.request_id), ['old', 'new']);
});

test('clearing pending audio keeps the active task tracked and prevents overlap', async () => {
  const queue = new TaskQueue(0);
  const audio = gate();
  const events = [];
  queue.addTask(async () => { events.push('first'); await audio.promise; events.push('ended'); });
  queue.addTask(async () => { events.push('discarded'); });
  queue.clearQueue();
  queue.addTask(async () => { events.push('second'); });
  let drained = false;
  const done = queue.waitForCompletion().then(() => { drained = true; });
  await delay(20);
  assert.equal(drained, false);
  assert.deepEqual(events, ['first']);
  audio.release();
  await done;
  assert.deepEqual(events, ['first', 'ended', 'second']);
});

test('an explicit stop settles active audio once; stale cleanup cannot clear new audio', async () => {
  let stopped = 0;
  const fakeAudio = () => ({ pause() {}, load() {}, src: 'test.wav' });
  const first = fakeAudio();
  audioManager.setCurrentAudio(first, null, () => { stopped += 1; });
  audioManager.stopCurrentAudioAndLipSync();
  audioManager.stopCurrentAudioAndLipSync();
  assert.equal(stopped, 1);
  const next = fakeAudio();
  audioManager.setCurrentAudio(next, null, () => { stopped += 1; });
  audioManager.clearCurrentAudio(first);
  assert.equal(audioManager.hasCurrentAudio(), true);
  audioManager.clearCurrentAudio(next);
  assert.equal(stopped, 1);
  assert.equal(audioManager.hasCurrentAudio(), false);
});
