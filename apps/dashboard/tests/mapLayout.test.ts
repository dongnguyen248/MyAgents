import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  capPulses,
  centreTone,
  formatBadge,
  gaugeFraction,
  stationLevel,
  stationPositions,
  CENTER_X,
  CENTER_Y,
} from '../src/lib/mapLayout.ts';

test('stationPositions: single station sits at the top', () => {
  const [point] = stationPositions(1);
  assert.equal(Math.round(point.x), CENTER_X);
  assert.ok(point.y < CENTER_Y);
});

test('stationPositions: two stations face each other', () => {
  const [first, second] = stationPositions(2);
  assert.equal(Math.round(first.x), Math.round(second.x));
  assert.ok(first.y < CENTER_Y && second.y > CENTER_Y);
});

test('stationPositions: 9 and 10 stations have no duplicate points', () => {
  for (const count of [9, 10]) {
    const points = stationPositions(count);
    const keys = new Set(points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`));
    assert.equal(keys.size, count);
  }
});

test('stationPositions: zero stations yields no points', () => {
  assert.deepEqual(stationPositions(0), []);
});

test('gaugeFraction: clamps and rejects unusable percents', () => {
  assert.equal(gaugeFraction(0), 0);
  assert.equal(gaugeFraction(50), 0.5);
  assert.equal(gaugeFraction(100), 1);
  assert.equal(gaugeFraction(-20), 0);
  assert.equal(gaugeFraction(140), 1);
  assert.equal(gaugeFraction(Number.NaN), null);
  assert.equal(gaugeFraction(null), null);
});

test('stationLevel: faults win, then activity, then idle', () => {
  assert.equal(stationLevel({ running: 1, faults: 2 }, true), 'error');
  assert.equal(stationLevel({ running: 1, faults: 0 }, false), 'active');
  assert.equal(stationLevel({ running: 0, faults: 0 }, true), 'active');
  assert.equal(stationLevel({ running: 0, faults: 0 }, false), 'idle');
  assert.equal(stationLevel(undefined, false), 'idle');
});

test('formatBadge: hidden at zero, capped at 99+', () => {
  assert.equal(formatBadge(0), '');
  assert.equal(formatBadge(1), '1');
  assert.equal(formatBadge(99), '99');
  assert.equal(formatBadge(100), '99+');
});

test('capPulses: keeps the newest pulses up to the cap', () => {
  const pulses = [1, 2, 3, 4, 5];
  assert.deepEqual(capPulses(pulses, 3), [3, 4, 5]);
  assert.deepEqual(capPulses(pulses, 12), pulses);
  assert.deepEqual(capPulses(pulses, 0), []);
});

test('centreTone: maps run statuses to tones', () => {
  assert.equal(centreTone('FAILED'), 'failed');
  assert.equal(centreTone('ESCALATED'), 'warn');
  assert.equal(centreTone('UNKNOWN'), 'unknown');
  assert.equal(centreTone('COMPLETED'), 'done');
  assert.equal(centreTone('RUNNING'), 'normal');
});
