// Anti-autofill tests for the model settings form (FIX-1 continued,
// Stage 1). The form component itself cannot be imported here (the
// node:test runner does not transform JSX and the component pulls in
// the api layer), so the assertions run on the pure attribute helper
// plus a static scan of the component source proving every input in
// the form actually uses it.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  API_KEY_INPUT_ATTRS,
  BASE_URL_INPUT_NAME,
  SHARED_MODEL_INPUT_NAME,
  agentModelInputName,
  modelTextInputAttrs,
} from '../src/components/settings/modelFormAttrs.ts';

const AGENT_KEYS = ['spec', 'plan', 'task', 'implement', 'review', 'fix'];

test('every text input name is the specified unique non-credential name', () => {
  assert.equal(SHARED_MODEL_INPUT_NAME, 'asf-model-shared');
  assert.equal(BASE_URL_INPUT_NAME, 'asf-base-url');
  const names = [
    SHARED_MODEL_INPUT_NAME,
    BASE_URL_INPUT_NAME,
    ...AGENT_KEYS.map(agentModelInputName),
  ];
  assert.equal(new Set(names).size, names.length);
  for (const name of names) {
    assert.ok(name.length > 0);
  }
  for (const name of [SHARED_MODEL_INPUT_NAME, ...AGENT_KEYS.map(agentModelInputName)]) {
    assert.ok(name.startsWith('asf-model-'), name);
  }
  assert.deepEqual(
    AGENT_KEYS.map(agentModelInputName),
    AGENT_KEYS.map((key) => `asf-model-${key}`),
  );
});

test('text input attrs opt out of autocomplete, spellcheck and autocapitalise', () => {
  for (const name of [SHARED_MODEL_INPUT_NAME, BASE_URL_INPUT_NAME, 'asf-model-fix']) {
    const attrs = modelTextInputAttrs(name);
    assert.equal(attrs.name, name);
    assert.equal(attrs.autoComplete, 'off');
    assert.equal(attrs.spellCheck, false);
    assert.equal(attrs.autoCapitalize, 'off');
    assert.equal(attrs.autoCorrect, 'off');
  }
});

test('api key attrs use new-password, a non-credential name and manager ignore flags', () => {
  assert.equal(API_KEY_INPUT_ATTRS.name, 'asf-provider-api-key');
  assert.equal(API_KEY_INPUT_ATTRS.autoComplete, 'new-password');
  assert.equal(API_KEY_INPUT_ATTRS['data-1p-ignore'], true);
  assert.equal(API_KEY_INPUT_ATTRS['data-lpignore'], 'true');
  assert.equal(API_KEY_INPUT_ATTRS['data-bwignore'], 'true');
  assert.equal(API_KEY_INPUT_ATTRS['data-form-type'], 'other');
});

// The LLM page splits its inputs across three components, so the scan runs
// per file: every text input must still carry {...modelTextInputAttrs(...)}
// and the one password input must carry {...API_KEY_INPUT_ATTRS}.
function inputBlocks(relativePath: string): string[] {
  const source = readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
  return source.match(/<input[\s\S]*?\/>/g) ?? [];
}

function textInputsOf(relativePath: string): string[] {
  return inputBlocks(relativePath).filter(
    (block) => !block.includes('type="password"') && !block.includes('type="checkbox"'),
  );
}

test('provider, model and endpoint inputs carry the anti-autofill attributes', () => {
  const blocks = inputBlocks('src/components/llm/ProviderFields.tsx');
  // Shared model and base URL; the provider select is not an input.
  assert.equal(blocks.length, 2);
  for (const block of blocks) {
    assert.ok(block.includes('{...modelTextInputAttrs('), block);
  }
});

test('the per-agent model input is named after its agent key', () => {
  const blocks = textInputsOf('src/components/llm/AgentModelPanel.tsx');
  assert.equal(blocks.length, 1);
  assert.ok(blocks[0].includes('{...modelTextInputAttrs(agentModelInputName(field.key))}'));
});

test('the shared key input is a password field with manager ignore flags', () => {
  const blocks = inputBlocks('src/components/llm/SharedKeyFields.tsx');
  const passwords = blocks.filter((block) => block.includes('type="password"'));
  assert.equal(passwords.length, 1);
  assert.ok(passwords[0].includes('{...API_KEY_INPUT_ATTRS}'));
  assert.ok(!passwords[0].includes('autoComplete='));
  const checkboxes = blocks.filter((block) => block.includes('type="checkbox"'));
  assert.equal(checkboxes.length, 1);
  assert.equal(textInputsOf('src/components/llm/SharedKeyFields.tsx').length, 0);
});
