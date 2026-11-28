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

test('rule API encodes file paths and saves agent assignments', async () => {
  const original = globalThis.fetch;
  const requests: { url: string; method: string; body?: string }[] = [];
  globalThis.fetch = async (url, init) => {
    const method = init?.method ?? 'GET';
    requests.push({ url: String(url), method, body: init?.body as string | undefined });
    const data = String(url).includes('/agents/') ? { rules: ['team/my rule.md'] } : { content: 'text' };
    return new Response(JSON.stringify(data), { status: 200 });
  };
  try {
    const api = createHttpApi('/api');
    assert.equal(await api.readRuleFile('team/my rule.md'), 'text');
    await api.saveRuleFile('team/my rule.md', 'updated');
    assert.deepEqual(await api.saveAgentRules('agent-spec', ['team/my rule.md']), ['team/my rule.md']);
    assert.equal(requests[0].url, '/api/rules/files/team/my%20rule.md');
    assert.deepEqual(JSON.parse(requests[2].body!), { rules: ['team/my rule.md'] });
  } finally { globalThis.fetch = original; }
});

test('project rule selections are sent on create and update', async () => {
  const original = globalThis.fetch;
  const bodies: Record<string, any>[] = [];
  globalThis.fetch = async (_url, init) => {
    bodies.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ id: 'p', enabledRules: bodies.at(-1)?.enabledRules }), { status: 200 });
  };
  try {
    const api = createHttpApi('/api');
    const input = { id: 'p', name: 'P', repository: { provider: 'gitlab' }, technology: { backend: [], frontend: [] }, workflow: 'software-development', enabledSkills: [], enabledRules: ['team.md'], configuration: {} };
    await api.createProject(input);
    await api.updateProject('p', { ...input, enabledRules: [] });
    assert.deepEqual(bodies.map((body) => body.enabledRules), [['team.md'], []]);
  } finally { globalThis.fetch = original; }
});
