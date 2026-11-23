import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildConnectionInput,
  buildConnectionsPayload,
  connStateFromView,
  ownKeyPlaceholder,
  ownKeyStatusText,
  parseHeadersText,
  sharedKeyStatusText,
} from '../src/lib/agentConnections.ts';
import type { AgentConnectionView } from '../src/types/settings.ts';

const VIEW: AgentConnectionView = {
  provider: 'custom',
  baseUrl: 'https://spec.example/v1',
  keyConfigured: true,
  keyHint: '…9999',
  headers: { 'X-Proxy-Token': '****' },
  timeoutSeconds: 30,
  insecureHttp: false,
};

test('headers text parses name/value lines and rejects malformed lines', () => {
  assert.deepEqual(parseHeadersText('X-A: 1\n\nX-B: two: colons\n'), {
    'X-A': '1',
    'X-B': 'two: colons',
  });
  assert.throws(() => parseHeadersText('no colon here'));
});

test('an untouched form produces no payload', () => {
  const state = connStateFromView(VIEW);
  assert.equal(buildConnectionInput(state, VIEW), null);
  assert.equal(buildConnectionsPayload({ spec: state }, { spec: VIEW }), undefined);
});

test('changed fields only, key write-only, removal is an empty object', () => {
  const state = connStateFromView(VIEW);
  state.baseUrl = 'http://127.0.0.1:18610/v1';
  state.timeoutText = '';
  assert.deepEqual(buildConnectionInput(state, VIEW), {
    baseUrl: 'http://127.0.0.1:18610/v1',
    timeoutSeconds: null,
  });
  const withKey = connStateFromView(VIEW);
  withKey.apiKey = 'fresh-key';
  assert.deepEqual(buildConnectionInput(withKey, VIEW), { apiKey: 'fresh-key' });
  const removed = connStateFromView(VIEW);
  removed.remove = true;
  assert.deepEqual(buildConnectionInput(removed, VIEW), {});
});

test('edited headers replace the set; a bad timeout is rejected', () => {
  const state = connStateFromView(undefined);
  state.headersText = 'X-Client: asf';
  state.headersDirty = true;
  assert.deepEqual(buildConnectionInput(state, undefined), {
    headers: { 'X-Client': 'asf' },
  });
  const bad = connStateFromView(undefined);
  bad.timeoutText = 'abc';
  assert.throws(() => buildConnectionInput(bad, undefined));
});

test('key status text and placeholders reflect own key and shared key state', () => {
  // 1. Per-agent connection with key configured
  assert.equal(ownKeyStatusText(VIEW), 'Own key saved (…9999)');
  assert.equal(ownKeyPlaceholder(VIEW), 'Leave blank to keep this agent’s key');

  // 2. Per-agent connection without key (fallback to shared)
  const noKeyView: AgentConnectionView = {
    ...VIEW,
    keyConfigured: false,
    keyHint: '',
  };
  assert.equal(ownKeyStatusText(noKeyView), 'No own key — using shared key');
  assert.equal(ownKeyPlaceholder(noKeyView), 'No own key — using shared key');
  assert.equal(ownKeyStatusText(undefined), 'No own key — using shared key');
  assert.equal(ownKeyPlaceholder(undefined), 'No own key — using shared key');

  // 3. Shared key status text
  assert.equal(sharedKeyStatusText(true, '…1234'), 'Stored key (…1234)');
  assert.equal(sharedKeyStatusText(true, ''), 'Stored key (…)');
  assert.equal(sharedKeyStatusText(false, ''), 'No key stored yet');
});
