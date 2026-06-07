/**
 * Jest is scoped to the pure, non-React logic (SSE decoding, base64, Markdown
 * parsing). It uses a self-contained babel transform so it does NOT touch the
 * Expo/Metro babel pipeline used to build the app.
 */
module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/src'],
  testMatch: ['**/__tests__/**/*.test.ts'],
  transform: {
    '^.+\\.[jt]sx?$': [
      'babel-jest',
      {
        configFile: false,
        babelrc: false,
        presets: [
          ['@babel/preset-env', { targets: { node: 'current' } }],
          '@babel/preset-typescript',
        ],
      },
    ],
  },
};
