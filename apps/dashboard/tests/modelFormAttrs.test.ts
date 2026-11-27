// Anti-autofill tests for the LLM profile form (FIX-1 continued,
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
  PROFILE_NAME_INPUT_NAME,
  modelTextInputAttrs,
} from '../src/components/settings/modelFormAttrs.ts';

test('every text input name is the specified unique non-credential name', () => {
  assert.equal(PROFILE_NAME_INPUT_NAME, 'asf-llm-profile-name');
  assert.equal(BASE_URL_INPUT_NAME, 'asf-base-url');
  const names = [PROFILE_NAME_INPUT_NAME, BASE_URL_INPUT_NAME];
  assert.equal(new Set(names).size, names.length);
  for (const name of names) {
    assert.ok(name.length > 0);
    assert.ok(name.startsWith('asf-'), name);
  }
});

test('text input attrs opt out of autocomplete, spellcheck and autocapitalise', () => {
  for (const name of [PROFILE_NAME_INPUT_NAME, BASE_URL_INPUT_NAME]) {
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

// The API-key toggle and the key input live in the same component as the
// name and endpoint inputs, so one scan covers the whole profile form.
function inputBlocks(relativePath: string): string[] {
  const source = readFileSync(new URL(`../${relativePath}`, import.meta.url), 'utf8');
  return source.match(/<input[\s\S]*?\/>/g) ?? [];
}

function isPassword(block: string): boolean {
  return block.includes('type="password"');
}

function isCheckbox(block: string): boolean {
  return block.includes('type="checkbox"');
}

test('name, endpoint and key inputs carry the anti-autofill attributes', () => {
  const blocks = inputBlocks('src/components/llm/ProfileFields.tsx');
  const passwords = blocks.filter(isPassword);
  const checkboxes = blocks.filter(isCheckbox);
  const texts = blocks.filter((block) => !isPassword(block) && !isCheckbox(block));
  // The key-clear toggle is the only checkbox; the model is a <select>.
  assert.equal(checkboxes.length, 1);
  assert.equal(passwords.length, 1);
  assert.ok(passwords[0].includes('{...API_KEY_INPUT_ATTRS}'));
  assert.ok(!passwords[0].includes('autoComplete='));
  assert.equal(texts.length, 2);
  for (const block of texts) {
    assert.ok(block.includes('{...modelTextInputAttrs('), block);
  }
  const names = texts.map((block) => block.match(/modelTextInputAttrs\(([A-Z_]+)\)/)?.[1]);
  assert.deepEqual(names, ['PROFILE_NAME_INPUT_NAME', 'BASE_URL_INPUT_NAME']);
});
