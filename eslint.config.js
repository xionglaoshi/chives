import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/dist/**',
      '**/node_modules/**',
      '**/coverage/**',
      'acceptance/**',
      'bots/**',
      'config/**',
      'core/**',
      'docs/**',
      'fixtures/**',
      'gateways/**',
      'overlays/**',
      'patches/**',
      'presets/**',
      'reports/**',
      'reviews/**',
      'runs/**',
      'runtime/**',
      'scripts/**',
      'skills/**',
      'tasks/**',
      'packages/cn-extra-mcp/**',
      'packages/cn-research-mcp/**',
      'packages/cn-watch/**',
      'packages/cn-watch-mcp/**',
      'packages/cn-watch-trigger/**',
      'packages/finance-bundle/**',
      'packages/fmp-mcp/**',
      'packages/hub-mcp/**',
      'packages/hub-trigger/**',
      'packages/market-watch/**',
      'packages/market-watch-mcp/**',
      'packages/mcp-filter-proxy/**',
      'packages/chives-hub/**',
      'packages/chives-ui/**',
      'packages/openbb-gateway/**',
      'packages/paper-broker-mcp/**',
      'packages/portfolio-mcp/**',
      'packages/profile-mcp/**',
      'packages/scrape-mcp/**',
      'packages/tavily-mcp/**',
      'packages/watch-panel/**',
      'packages/x-mcp/**'
    ]
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: [
      'apps/server/**/*.ts',
      'packages/acp-client/**/*.ts',
      'packages/chives-mcp/**/*.ts'
    ],
    languageOptions: {
      globals: globals.node
    },
    rules: {
      'no-undef': 'off'
    }
  },
  {
    files: ['apps/web/**/*.{ts,tsx}'],
    languageOptions: {
      globals: globals.browser
    },
    rules: {
      'no-undef': 'off'
    }
  }
);
