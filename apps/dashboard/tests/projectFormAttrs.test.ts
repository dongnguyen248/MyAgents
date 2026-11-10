// Anti-autofill attributes for the project form: the shared helpers'
// values, and a static scan that ProjectForm spreads them onto the
// two inputs at risk (the repository URL text input sits in the
// "username" slot right before the hosting-token password input).
// Same approach as tests/modelFormAttrs.test.ts: the node:test
// runner cannot import the .tsx component, so the component wiring
// is asserted on its source.
// Run with: npm test  (node:test + type stripping, no extra deps)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { secretInputAttrs, textInputAttrs } from '../src/components/forms/inputAttrs.ts';

test('text inputs opt out of autocomplete and spellcheck under their name', () => {
  assert.deepEqual(textInputAttrs('asf-repo-url'), {
    name: 'asf-repo-url',
    autoComplete: 'off',
    spellCheck: false,
    autoCapitalize: 'off',
    autoCorrect: 'off',
  });
});

test('secret inputs present as a new password with manager ignore flags', () => {
  assert.deepEqual(secretInputAttrs('asf-hosting-token'), {
    name: 'asf-hosting-token',
    autoComplete: 'new-password',
    'data-1p-ignore': true,
    'data-lpignore': 'true',
    'data-bwignore': 'true',
    'data-form-type': 'other',
  });
});

const source = readFileSync(
  new URL('../src/components/projects/ProjectForm.tsx', import.meta.url),
  'utf8',
);

test('ProjectForm spreads the shared attributes on the URL and token inputs', () => {
  assert.match(source, /\{\.\.\.textInputAttrs\('asf-repo-url'\)\}/);
  assert.match(source, /\{\.\.\.secretInputAttrs\('asf-hosting-token'\)\}/);
  const passwordInputs = source.match(/type="password"/g) ?? [];
  assert.equal(passwordInputs.length, 1);
  assert.doesNotMatch(source, /autoComplete="off"\s*\n\s*\/>/);
});
