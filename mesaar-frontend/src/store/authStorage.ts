import AsyncStorage from '@react-native-async-storage/async-storage';
import type { DriverProfile } from '../api/types';
import { BASE_URL, USE_MOCK } from '../api/client';

/**
 * Lightweight persisted session. In production the token should live in
 * expo-secure-store; AsyncStorage is used here as a dependency-light default
 * and keeps the driver signed in across app restarts.
 */
const PREFIX = `mesaar.${USE_MOCK ? 'demo' : 'live'}.${BASE_URL}`;
const TOKEN_KEY = `${PREFIX}.token`;
const DRIVER_KEY = `${PREFIX}.driver`;
const REFRESH_KEY = `${PREFIX}.refresh`;

export interface PersistedSession {
  token: string;
  driver: DriverProfile;
  refreshToken?: string;
}

export async function persistSession(session: PersistedSession): Promise<void> {
  await AsyncStorage.multiSet([
    [TOKEN_KEY, session.token],
    [DRIVER_KEY, JSON.stringify(session.driver)],
    [REFRESH_KEY, session.refreshToken ?? ''],
  ]);
}

export async function loadSession(): Promise<PersistedSession | null> {
  try {
    const [[, token], [, driverRaw], [, refreshToken]] = await AsyncStorage.multiGet([
      TOKEN_KEY,
      DRIVER_KEY,
      REFRESH_KEY,
    ]);
    if (!token || !driverRaw) return null;
    if (!USE_MOCK && token.startsWith('mock.')) return null;
    const driver = JSON.parse(driverRaw) as DriverProfile;
    if (!driver.id || !driver.userId) return null;
    return { token, driver, refreshToken: refreshToken || undefined };
  } catch {
    return null;
  }
}

export async function clearSession(): Promise<void> {
  await AsyncStorage.multiRemove([TOKEN_KEY, DRIVER_KEY, REFRESH_KEY]);
}
