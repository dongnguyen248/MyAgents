import assert from 'node:assert/strict';
import test from 'node:test';
import { createHttpApi } from '../src/services/api/httpApi.ts';

const settings = {
  provider: 'openai', model: 'shared-model', baseUrl: '', keyConfigured: true,
  agentModels: { plan: 'plan-model', implement: 'old-model' },
  agentConnections: { plan: { provider: 'custom', keyConfigured: true } },
};

test('agent model save keeps other agent overrides and does not send masked keys', async () => {
  const original = globalThis.fetch;
  let payload: Record<string, any> | undefined;
  globalThis.fetch = async (_url, init) => {
    if (init?.method === 'PUT') { payload = JSON.parse(String(init.body)); }
    return new Response(JSON.stringify(settings), { status: 200 });
  };
  try {
    const api = createHttpApi('/api');
    await api.saveAgentModel({ agent: 'implement', provider: 'custom', baseUrl: 'https://example.com/v1', model: 'new-model' });
    assert.deepEqual(payload?.agentModels, { plan: 'plan-model', implement: 'new-model' });
    assert.deepEqual(payload?.agentConnections, { implement: { provider: 'custom', baseUrl: 'https://example.com/v1' } });
    assert.equal(payload?.apiKey, undefined);
    assert.equal(payload?.provider, 'openai');
  } finally { globalThis.fetch = original; }
});

test('agent model and skills surface backend errors', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 404 });
  try {
    const api = createHttpApi('/api');
    await assert.rejects(api.getModelSettings(), /Unavailable/);
    await assert.rejects(api.getAgentSkills('agent-spec'), /Unavailable/);
  } finally { globalThis.fetch = original; }
});
