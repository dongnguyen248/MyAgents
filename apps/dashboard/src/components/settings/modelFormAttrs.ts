/**
 * Input attributes that keep browsers and password managers out of
 * the LLM profile form. The form holds an API key (a password
 * input), which makes browsers treat the neighbouring text inputs
 * as credential fields: the profile name or base URL can be
 * autofilled with a saved username, which a later Save then
 * persists into the profile. Unique non-credential names,
 * autocomplete opt-outs and the password manager ignore flags
 * below are the defence; they change no behaviour of the form
 * itself. The same attribute sets live in
 * components/forms/inputAttrs for the other forms; this module
 * keeps its own copy because its test imports it under the
 * node:test runner, which cannot follow extensionless value
 * imports, and tsconfig forbids .ts-extension imports in src.
 */

/** Attributes for one plain-text input with the given name. */
export function modelTextInputAttrs(name: string) {
  return {
    name,
    autoComplete: 'off',
    spellCheck: false,
    autoCapitalize: 'off',
    autoCorrect: 'off',
  };
}

/** The profile form's name for the operator-facing profile name. */
export const PROFILE_NAME_INPUT_NAME = 'asf-llm-profile-name';

/** The profile form's name for the endpoint base URL. */
export const BASE_URL_INPUT_NAME = 'asf-base-url';

/**
 * Attributes for the API key input: a "new password" (never a saved
 * login password to autofill from), under a name no credential
 * manager recognises, with the common ignore flags for 1Password,
 * LastPass and Bitwarden.
 */
export const API_KEY_INPUT_ATTRS = {
  name: 'asf-provider-api-key',
  autoComplete: 'new-password',
  'data-1p-ignore': true,
  'data-lpignore': 'true',
  'data-bwignore': 'true',
  'data-form-type': 'other',
} as const;
