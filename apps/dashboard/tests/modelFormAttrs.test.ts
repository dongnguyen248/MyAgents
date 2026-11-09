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

function inputBlocks(): string[] {
  const source = readFileSync(
    new URL('../src/components/settings/ModelProviderForm.tsx', import.meta.url),
    'utf8',
  );
  return source.match(/<input[\s\S]*?\/>/g) ?? [];
}

test('every input in the form carries the anti-autofill attributes', () => {
  const blocks = inputBlocks();
  // Shared model, base URL, the per-agent input (rendered per agent),
  // the API key and the clear-key checkbox.
  assert.equal(blocks.length, 5);
  const passwords = blocks.filter((block) => block.includes('type="password"'));
  assert.equal(passwords.length, 1);
  assert.ok(passwords[0].includes('{...API_KEY_INPUT_ATTRS}'));
  assert.ok(!passwords[0].includes('autoComplete='));
  const checkboxes = blocks.filter((block) => block.includes('type="checkbox"'));
  assert.equal(checkboxes.length, 1);
  const textInputs = blocks.filter(
    (block) => !block.includes('type="password"') && !block.includes('type="checkbox"'),
  );
  assert.equal(textInputs.length, 3);
  for (const block of textInputs) {
    assert.ok(block.includes('{...modelTextInputAttrs('), block);
  }
  const agentInput = textInputs.find((block) => block.includes('agentModelInputName(a.key)'));
  assert.ok(agentInput);
});
