/**
 * Input attributes that keep browsers and password managers out of
 * forms holding a secret in a password input. Such a form makes
 * browsers treat the neighbouring text inputs as credential
 * fields: the text input right before the password input sits in
 * the "username" slot and can be autofilled with a saved username,
 * which a later Save then persists as data (the model settings
 * form's Fix model field is how this was found). Unique
 * non-credential names, autocomplete opt-outs and the password
 * manager ignore flags below are the defence; they change no
 * behaviour of the forms themselves. The model settings form
 * keeps its own copy of these sets in
 * components/settings/modelFormAttrs (its test imports that
 * module under the node:test runner, which cannot follow
 * extensionless value imports); change both together.
 */

/** Attributes for one plain-text input with the given name. */
export function textInputAttrs(name: string) {
  return {
    name,
    autoComplete: 'off',
    spellCheck: false,
    autoCapitalize: 'off',
    autoCorrect: 'off',
  };
}

/**
 * Attributes for a secret input: a "new password" (never a saved
 * login password to autofill from), under a name no credential
 * manager recognises, with the common ignore flags for 1Password,
 * LastPass and Bitwarden.
 */
export function secretInputAttrs(name: string) {
  return {
    name,
    autoComplete: 'new-password',
    'data-1p-ignore': true,
    'data-lpignore': 'true',
    'data-bwignore': 'true',
    'data-form-type': 'other',
  } as const;
}
