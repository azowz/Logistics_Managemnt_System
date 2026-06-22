/**
 * Typography scale. The app loads the Tajawal Arabic family (see useAppFonts);
 * we fall back to the platform system font until/if fonts fail to load so the
 * UI never blocks on the network.
 */
export const fonts = {
  regular: 'Tajawal_400Regular',
  medium: 'Tajawal_500Medium',
  bold: 'Tajawal_700Bold',
  black: 'Tajawal_800ExtraBold',
} as const;

export const typography = {
  display: { fontFamily: fonts.black, fontSize: 30, lineHeight: 40 },
  h1: { fontFamily: fonts.bold, fontSize: 24, lineHeight: 34 },
  h2: { fontFamily: fonts.bold, fontSize: 20, lineHeight: 30 },
  h3: { fontFamily: fonts.bold, fontSize: 17, lineHeight: 26 },
  bodyStrong: { fontFamily: fonts.medium, fontSize: 15, lineHeight: 24 },
  body: { fontFamily: fonts.regular, fontSize: 15, lineHeight: 24 },
  caption: { fontFamily: fonts.regular, fontSize: 13, lineHeight: 20 },
  micro: { fontFamily: fonts.medium, fontSize: 11, lineHeight: 16 },
  numeric: { fontFamily: fonts.black, fontSize: 22, lineHeight: 28 },
} as const;
