import {expect, jest, test} from '@jest/globals';

const mockDefaults = {
  resolver: {sourceExts:['ts','tsx']},
  transformer: {fixture:true},
  serializer: {getPolyfills: jest.fn(() => ['web-default']), other:'keep'},
};
jest.mock('expo/metro-config', () => ({getDefaultConfig: () => mockDefaults}));
jest.mock('@react-native/js-polyfills', () => () => ['native-console','native-error'], {virtual:true});

test.each(['android','ios'])('uses the official polyfill entry for %s', platform => {
  const config = require('../../metro.config');
  expect(config.serializer.getPolyfills({platform})).toEqual(['native-console','native-error']);
});
test('preserves Expo defaults and web behavior', () => {
  const config = require('../../metro.config');
  expect(config.resolver).toBe(mockDefaults.resolver);
  expect(config.transformer).toBe(mockDefaults.transformer);
  expect(config.serializer.other).toBe('keep');
  expect(config.serializer.getPolyfills({platform:'web'})).toEqual(['web-default']);
  expect(config.serializer.getPolyfills({platform:null})).toEqual([]);
});
