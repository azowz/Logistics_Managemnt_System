import AsyncStorage from '@react-native-async-storage/async-storage';
import type { DriverProfile } from '../api/types';

/**
 * Lightweight persisted session. In production the token should live in
 * expo-secure-store; AsyncStorage is used here as a dependency-light default
 * and keeps the driver signed in across app restarts.
 */
const TOKEN_KEY = 'mesaar.auth.token';
const DRIVER_KEY = 'mesaar.auth.driver';

export interface PersistedSession {
  token: string;
  driver: DriverProfile;
}

export async function persistSession(session: PersistedSession): Promise<void> {
  await AsyncStorage.multiSet([
    [TOKEN_KEY, session.token],
    [DRIVER_KEY, JSON.stringify(session.driver)],
  ]);
}

export async function loadSession(): Promise<PersistedSession | null> {
  try {
    const [[, token], [, driverRaw]] = await AsyncStorage.multiGet([
      TOKEN_KEY,
      DRIVER_KEY,
    ]);
    if (!token || !driverRaw) return null;
    return { token, driver: JSON.parse(driverRaw) as DriverProfile };
  } catch {
    return null;
  }
}

export async function clearSession(): Promise<void> {
  await AsyncStorage.multiRemove([TOKEN_KEY, DRIVER_KEY]);
}
