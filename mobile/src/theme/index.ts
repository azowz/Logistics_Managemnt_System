export { colors } from './colors';
export type { AppColors } from './colors';
export { spacing, radius, shadow } from './spacing';
export { typography, fonts } from './typography';

export const theme = {
  // Standard horizontal screen gutter.
  screenPadding: 20,
  // iPhone reference width used by mock-ups; layout is fluid, not fixed.
  referenceWidth: 390,
} as const;
