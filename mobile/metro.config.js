// RN 0.87 removed rn-get-polyfills. Keep Expo's serializer and resolver defaults;
// use the documented replacement only for the two native targets.
const {getDefaultConfig} = require('expo/metro-config');
const config = getDefaultConfig(__dirname);
const expoPolyfills = config.serializer.getPolyfills;
config.serializer.getPolyfills = options => {
  if (!options.platform) return [];
  if (options.platform === 'android' || options.platform === 'ios') {
    return require('@react-native/js-polyfills')();
  }
  return expoPolyfills(options);
};
module.exports = config;
