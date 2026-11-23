// Pure-function tests for the live map board (src/lib/mapBoard.ts).
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  agentStates,
  applyMapEvent,
  applyMapEvents,
  budgetPercent,
  childrenOf,
  emptyBoard,
  feedRows,
  stationCounts,
} from '../src/lib/mapBoard.ts';
import type { MapEvent } from '../src/types/map.ts';

function event(partial: Partial<MapEvent>): MapEvent {
  return {
    id: 'e1',
    ts: '2026-11-23T09:00:00Z',
    runId: 'run-1',
    spanId: 'span-1',
    type: 'model',
    station: 'model',
    phase: 'start',
    status: 'running',
    label: 'fake-1',
    ...partial,
  };
}

test('a start and its end fold into one closed entry', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({ id: 'e1', phase: 'start', status: 'running' }),
    event({
      id: 'e2',
      phase: 'end',
      status: 'ok',
      ts: '2026-11-23T09:00:05Z',
      durationMs: 5000,
      promptTokens: 120,
      completionTokens: 30,
    }),
  ]);
  assert.equal(board.entries.length, 1);
  const entry = board.entries[0];
  assert.equal(entry.status, 'ok');
  assert.equal(entry.durationMs, 5000);
  assert.equal(entry.promptTokens, 120);
  assert.equal(entry.endedAt, '2026-11-23T09:00:05Z');
});

test('a duplicate start for one span is ignored', () => {
  const board = applyMapEvents(emptyBoard(), [event({ id: 'e1' }), event({ id: 'e2' })]);
  assert.equal(board.entries.length, 1);
});

test('an end without a start still lands as a closed entry', () => {
  const board = applyMapEvent(
    emptyBoard(),
    event({ phase: 'end', status: 'error', errorCode: 'X' }),
  );
  assert.equal(board.entries.length, 1);
  assert.equal(board.entries[0].status, 'error');
  assert.equal(board.entries[0].errorCode, 'X');
});

test('station counts track totals, running and faults', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({ id: 'e1', spanId: 's1' }),
    event({ id: 'e2', spanId: 's2', phase: 'end', status: 'error' }),
    event({
      id: 'e3',
      spanId: 's3',
      station: 'gates',
      type: 'gate',
      phase: 'moment',
      status: 'blocked',
      label: 'gate',
    }),
  ]);
  const counts = stationCounts(board);
  assert.deepEqual(counts.model, { total: 2, running: 1, faults: 1 });
  assert.deepEqual(counts.gates, { total: 1, running: 0, faults: 1 });
});

test('feed folds consecutive finished rows at one station for one agent', () => {
  const pulses: MapEvent[] = [];
  for (let i = 0; i < 3; i += 1) {
    pulses.push(
      event({
        id: `e${i}`,
        spanId: `s${i}`,
        phase: 'end',
        status: 'ok',
        agentId: 'agent-plan',
        ts: `2026-11-23T09:00:0${i}Z`,
      }),
    );
  }
  pulses.push(
    event({
      id: 'e9',
      spanId: 's9',
      station: 'gates',
      type: 'gate',
      phase: 'moment',
      status: 'ok',
      label: 'gate',
      ts: '2026-11-23T09:00:09Z',
    }),
  );
  const rows = feedRows(applyMapEvents(emptyBoard(), pulses), null);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].entry.station, 'gates');
  assert.equal(rows[1].times, 3);
});

test('feed filter keeps only the chosen agent', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({ id: 'e1', spanId: 's1', agentId: 'agent-spec', phase: 'end', status: 'ok' }),
    event({
      id: 'e2',
      spanId: 's2',
      agentId: 'agent-plan',
      phase: 'end',
      status: 'ok',
      ts: '2026-11-23T09:01:00Z',
    }),
  ]);
  const rows = feedRows(board, 'agent-plan');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].entry.agentId, 'agent-plan');
});

test('agent states derive from agent entries only', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({
      id: 'e1',
      spanId: 'a1',
      type: 'agent',
      station: 'agents',
      agentId: 'agent-spec',
      phase: 'start',
      status: 'running',
      label: 'agent-spec',
    }),
    event({
      id: 'e2',
      spanId: 'a1',
      type: 'agent',
      station: 'agents',
      agentId: 'agent-spec',
      phase: 'end',
      status: 'ok',
      durationMs: 2000,
      label: 'agent-spec',
    }),
    event({ id: 'e3', spanId: 'm1', agentId: 'agent-spec', phase: 'end', status: 'ok' }),
  ]);
  const states = agentStates(board);
  assert.equal(states.length, 1);
  assert.equal(states[0].status, 'done');
  assert.equal(states[0].calls, 1);
  assert.equal(states[0].totalMs, 2000);
});

test('childrenOf finds the model calls under an agent span', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({
      id: 'e1',
      spanId: 'req-1',
      type: 'agent',
      station: 'agents',
      agentId: 'agent-spec',
      label: 'agent-spec',
    }),
    event({
      id: 'e2',
      spanId: 'req-1:model:1',
      parentId: 'req-1',
      agentId: 'agent-spec',
      phase: 'end',
      status: 'ok',
    }),
  ]);
  const children = childrenOf(board, 'req-1');
  assert.equal(children.length, 1);
  assert.equal(children[0].spanId, 'req-1:model:1');
});

test('budgetPercent is null without a limit and capped at 100', () => {
  assert.equal(budgetPercent(500, null), null);
  assert.equal(budgetPercent(500, 1000), 50);
  assert.equal(budgetPercent(1500, 1000), 100);
});
