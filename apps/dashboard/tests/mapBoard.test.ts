// Pure-function tests for the live map board (src/lib/mapBoard.ts).
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  agentColor,
  agentStates,
  applyMapEvent,
  applyMapEvents,
  budgetPercent,
  childrenOf,
  emptyBoard,
  feedItems,
  feedRows,
  isModelFlashing,
  modelChanges,
  runningAgents,
  replayBoard,
  replayDurationMs,
  spokeWidth,
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

test('stationCounts prefers hub counters over the visible entries', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({ id: 'e1', phase: 'end', status: 'error' }),
    event({ id: 'e2', spanId: 'span-2', phase: 'start', status: 'running' }),
  ]);
  const fromEntries = stationCounts(board);
  assert.equal(fromEntries.model?.total, 2);
  const counters = { stations: { model: 1500 }, agents: {}, errors: { model: 40 } };
  const fromCounters = stationCounts(board, counters);
  assert.equal(fromCounters.model?.total, 1500);
  assert.equal(fromCounters.model?.faults, 40);
  assert.equal(fromCounters.model?.running, 1);
});

test('consecutive tool calls fold by station even with different labels', () => {
  const tool = (id: string, spanId: string, label: string, ts: string) =>
    event({
      id,
      spanId,
      ts,
      type: 'tool',
      station: 'files',
      phase: 'end',
      status: 'ok',
      label,
      agentId: 'agent-task',
    });
  const board = applyMapEvents(emptyBoard(), [
    tool('e1', 's1', 'api/demo.py', '2026-11-23T09:00:01Z'),
    tool('e2', 's2', 'api/routes.py', '2026-11-23T09:00:02Z'),
    tool('e3', 's3', 'tools/local.py', '2026-11-23T09:00:03Z'),
  ]);
  const rows = feedRows(board, null);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].times, 3);
});

test('spokeWidth grows with use and is capped', () => {
  assert.equal(spokeWidth(0), 1.5);
  assert.equal(spokeWidth(25), 3.5);
  assert.equal(spokeWidth(10000), 5.5);
});

function modelSpan(id: string, spanId: string, model: string, ts: string) {
  return event({ id, spanId, type: 'model', station: 'model', model, label: model, ts });
}

test('model changes are detected between consecutive model spans of the run', () => {
  const board = applyMapEvents(emptyBoard(), [
    modelSpan('e1', 's1', 'model-a', '2026-11-23T09:00:00Z'),
    modelSpan('e2', 's2', 'model-a', '2026-11-23T09:01:00Z'),
    modelSpan('e3', 's3', 'model-b', '2026-11-23T09:02:00Z'),
    event({ id: 'e4', spanId: 's4', type: 'agent', station: 'agents', ts: '2026-11-23T09:03:00Z' }),
  ]);
  const changes = modelChanges(board);
  assert.equal(changes.length, 1);
  assert.equal(changes[0].fromModel, 'model-a');
  assert.equal(changes[0].toModel, 'model-b');
  assert.equal(changes[0].at, '2026-11-23T09:02:00Z');
});

test('feed items interleave model-change markers with rows, newest first', () => {
  const board = applyMapEvents(emptyBoard(), [
    modelSpan('e1', 's1', 'model-a', '2026-11-23T09:00:00Z'),
    modelSpan('e2', 's2', 'model-b', '2026-11-23T09:05:00Z'),
  ]);
  const items = feedItems(board, null);
  assert.equal(items[0].kind, 'change');
  assert.equal(items.filter((item) => item.kind === 'change').length, 1);
});

test('the model flash lasts only while the change is fresh on the board timeline', () => {
  const fresh = applyMapEvents(emptyBoard(), [
    modelSpan('e1', 's1', 'model-a', '2026-11-23T09:00:00Z'),
    modelSpan('e2', 's2', 'model-b', '2026-11-23T09:00:02Z'),
  ]);
  assert.equal(isModelFlashing(fresh), true);
  const stale = applyMapEvents(fresh, [
    event({ id: 'e3', spanId: 's3', type: 'agent', station: 'agents', ts: '2026-11-23T09:01:00Z' }),
  ]);
  assert.equal(isModelFlashing(stale), false);
  assert.equal(isModelFlashing(emptyBoard()), false);
});

test('running agents list one orbit entry per in-flight execution, coloured per agent', () => {
  const board = applyMapEvents(emptyBoard(), [
    event({ id: 'e1', spanId: 'a1', type: 'agent', station: 'agents', agentId: 'spec' }),
    event({ id: 'e2', spanId: 'a2', type: 'agent', station: 'agents', agentId: 'implement' }),
    event({ id: 'e3', spanId: 'a3', type: 'agent', station: 'agents', agentId: 'review' }),
    event({ id: 'e4', spanId: 'a3', type: 'agent', station: 'agents', phase: 'end', status: 'ok' }),
    event({ id: 'e5', spanId: 'm1', type: 'model', station: 'model' }),
  ]);
  const running = runningAgents(board);
  assert.deepEqual(
    running.map((agent) => agent.agentId),
    ['spec', 'implement'],
  );
  assert.equal(running[0].color, agentColor('spec'));
  assert.equal(runningAgents(emptyBoard()).length, 0);
});

test('a full replay rebuilds exactly the live board at the end of the run', () => {
  const events = [
    event({ id: 'e1', spanId: 'a1', type: 'agent', station: 'agents', agentId: 'spec' }),
    event({
      id: 'e2',
      spanId: 'm1',
      type: 'model',
      station: 'model',
      model: 'fake-1',
      ts: '2026-11-23T09:00:01Z',
    }),
    event({
      id: 'e3',
      spanId: 'm1',
      type: 'model',
      station: 'model',
      phase: 'end',
      status: 'ok',
      ts: '2026-11-23T09:00:04Z',
      durationMs: 3000,
    }),
    event({
      id: 'e4',
      spanId: 'a1',
      type: 'agent',
      station: 'agents',
      phase: 'end',
      status: 'ok',
      ts: '2026-11-23T09:00:05Z',
    }),
  ];
  const live = applyMapEvents(emptyBoard(), events);
  const replayed = replayBoard(events, replayDurationMs(events));
  assert.deepEqual(replayed, live);
  assert.equal(replayDurationMs(events), 5000);
});

test('a replay cursor shows only the pulses up to that point on the timeline', () => {
  const events = [
    event({ id: 'e1', spanId: 'a1', type: 'agent', station: 'agents', agentId: 'spec' }),
    event({
      id: 'e2',
      spanId: 'm1',
      type: 'model',
      station: 'model',
      model: 'fake-1',
      ts: '2026-11-23T09:00:03Z',
    }),
  ];
  const early = replayBoard(events, 1000);
  assert.equal(early.entries.length, 1);
  assert.equal(early.entries[0].type, 'agent');
  assert.equal(replayBoard(events, 0).entries.length, 1);
  assert.equal(replayBoard([], 1000).entries.length, 0);
});
