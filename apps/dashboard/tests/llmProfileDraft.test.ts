// The LLM profile form's pure half: ids, validation and the save payload.
// The dialog cannot be imported here (the node:test runner does not
// transform JSX), so these run on the lib the dialog is built from.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  draftFromProfile,
  draftProblem,
  emptyDraft,
  profileIdFor,
  profileInputOf,
} from '../src/lib/llmProfileDraft.ts';
import type { LlmProfile } from '../src/types/llm.ts';

const PROFILE: LlmProfile = {
  id: 'openai-primary',
  name: 'OpenAI · GPT-4o',
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  model: 'gpt-4o',
  models: ['gpt-4o', 'gpt-4o-mini'],
  keyConfigured: true,
  keyHint: '…a1b2',
};

function ready(model: string) {
  return { ...emptyDraft(), name: 'OpenAI · GPT-4o', model, apiKey: 'sk-test' };
}

test('a new profile id is a slug of the name, numbered when it collides', () => {
  assert.equal(profileIdFor('OpenAI · GPT-4o', []), 'openai-gpt-4o');
  assert.equal(profileIdFor('OpenAI · GPT-4o', ['openai-gpt-4o']), 'openai-gpt-4o-2');
  assert.equal(
    profileIdFor('OpenAI · GPT-4o', ['openai-gpt-4o', 'openai-gpt-4o-2']),
    'openai-gpt-4o-3',
  );
  assert.equal(profileIdFor('3rd party', []), 'p-3rd-party');
  assert.equal(profileIdFor('···', []), 'profile');
});

test('a profile is saveable only with a name and a model the endpoint offered', () => {
  assert.match(draftProblem(emptyDraft()) ?? '', /name/i);
  assert.match(draftProblem({ ...ready(''), name: 'Homelab' }) ?? '', /pick one/i);
  assert.equal(draftProblem(ready('gpt-4o')), undefined);
  assert.equal(draftProblem({ ...ready(''), provider: 'scripted' }), undefined);
});

test('a custom provider needs an http(s) base URL', () => {
  const custom = { ...ready('muse-chat'), provider: 'custom', baseUrl: '127.0.0.1:18610' };
  assert.match(draftProblem(custom) ?? '', /base URL/i);
  assert.equal(draftProblem({ ...custom, baseUrl: 'http://127.0.0.1:18610/v1' }), undefined);
});

test('the save payload is trimmed and leaves a blank key out', () => {
  const draft = {
    name: '  Homelab  ',
    provider: 'custom',
    baseUrl: ' http://127.0.0.1:18610/v1 ',
    apiKey: '',
    model: ' muse-chat ',
    clearKey: false,
  };
  assert.deepEqual(profileInputOf('homelab', draft), {
    id: 'homelab',
    name: 'Homelab',
    provider: 'custom',
    baseUrl: 'http://127.0.0.1:18610/v1',
    model: 'muse-chat',
  });
});

test('the loaded model list rides along so the select refills next time', () => {
  const input = profileInputOf('homelab', ready('gpt-4o'), ['gpt-4o', 'gpt-4o-mini']);
  assert.deepEqual(input.models, ['gpt-4o', 'gpt-4o-mini']);
  assert.equal(profileInputOf('homelab', ready('gpt-4o')).models, undefined);
});

test('a typed key is sent and a cleared key is flagged', () => {
  assert.equal(profileInputOf('homelab', ready('gpt-4o')).apiKey, 'sk-test');
  assert.equal(profileInputOf('homelab', { ...ready('gpt-4o'), clearKey: true }).clearKey, true);
});

test('editing starts from the stored profile with an empty key field', () => {
  assert.deepEqual(draftFromProfile(PROFILE), {
    name: 'OpenAI · GPT-4o',
    provider: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    apiKey: '',
    model: 'gpt-4o',
    clearKey: false,
  });
});
