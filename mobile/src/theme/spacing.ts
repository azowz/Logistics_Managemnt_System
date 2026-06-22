/** 4pt spacing scale used across paddings, gaps and margins. */
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 40,
} as const;

/** Corner radius tokens — cards sit in the 18–24 range per the design spec. */
export const radius = {
  sm: 10,
  md: 14,
  lg: 18,
  xl: 22,
  xxl: 28,
  pill: 999,
} as const;

/** Soft elevation shadow shared by raised cards (iOS + Android). */
export const shadow = {
  card: {
    shadowColor: '#000000',
    shadowOpacity: 0.35,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
    elevation: 8,
  },
  floating: {
    shadowColor: '#000000',
    shadowOpacity: 0.45,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: -6 },
    elevation: 16,
  },
} as const;
