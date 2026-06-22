// Default Expo Metro config. Kept explicit so SVG/asset resolution stays predictable.
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

module.exports = config;
