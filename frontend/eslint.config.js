// ESLint flat config (ESLint 10). Uses only packages already in devDependencies:
// eslint, @typescript-eslint/parser, @typescript-eslint/eslint-plugin.
import tsPlugin from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'

export default [
  {
    ignores: [
      'dist/**',
      'dist-e2e/**',
      'node_modules/**',
      'android/**',
      'ios/**',
      'dev-dist/**',
      'coverage/**',
    ],
  },
  // typescript-eslint recommended (flat): parser + plugin + rules for ts/tsx files
  ...tsPlugin.configs['flat/recommended'].map((c) => ({
    ...c,
    files: c.files ?? ['**/*.{ts,tsx}'],
  })),
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { parser: tsParser },
  },
]
