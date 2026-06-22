/**
 * Mesaar dark design system — color tokens.
 * Single source of truth for every surface and accent in the app.
 */
export const colors = {
  // Base canvas — deep navy-black "mission control" backdrop.
  background: '#090D14',
  backgroundElevated: '#0C111A',

  // Cards & raised surfaces.
  card: '#121821',
  cardElevated: '#161D29',
  cardMuted: '#0F151E',

  // Hairline borders.
  border: 'rgba(255,255,255,0.06)',
  borderStrong: 'rgba(255,255,255,0.12)',

  // Brand / actions.
  primary: '#2F6BFF',
  primaryPressed: '#2456D6',
  primarySoft: 'rgba(47,107,255,0.14)',

  // Status.
  success: '#18C56E',
  successPressed: '#13A85D',
  successSoft: 'rgba(24,197,110,0.14)',

  warning: '#FFB020',
  warningSoft: 'rgba(255,176,32,0.14)',

  danger: '#FF5A5F',
  dangerSoft: 'rgba(255,90,95,0.12)',

  // Typography.
  textPrimary: '#F4F7FB',
  textSecondary: '#7D8BA3',
  textMuted: '#5A6678',
  textOnPrimary: '#FFFFFF',

  // Map visuals.
  mapBase: '#0A0F18',
  mapGrid: 'rgba(255,255,255,0.04)',
  mapRoad: 'rgba(125,139,163,0.18)',
  routeLine: '#2F6BFF',
  routeGlow: 'rgba(47,107,255,0.35)',
  pickup: '#18C56E',
  dropoff: '#FF5A5F',
} as const;

export type AppColors = typeof colors;
