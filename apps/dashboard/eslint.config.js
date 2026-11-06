import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

// Phase 11a structure enforcement (Appendix A). Violations that
// predate the rules live in eslint-suppressions.json (the ratchet:
// it may only shrink, exactly like .code-structure-baseline.json);
// anything not suppressed fails CI.
export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [tseslint.configs.recommended],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      curly: ['error', 'all'],
      'no-nested-ternary': 'error',
      'max-statements-per-line': ['error', { max: 1 }],
      'max-lines-per-function': [
        'error',
        { max: 30, skipBlankLines: true, skipComments: true },
      ],
      complexity: ['error', 10],
      'max-params': ['error', 4],
      'max-depth': ['error', 3],
      'no-magic-numbers': [
        'error',
        { ignore: [-1, 0, 1, 2], ignoreArrayIndexes: true, detectObjects: false },
      ],
    },
  },
);
