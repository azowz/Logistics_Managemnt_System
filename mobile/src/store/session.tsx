import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { driverApi, setAuthToken } from '../api';
import type { DriverProfile } from '../api/types';
import { clearSession, loadSession, persistSession } from './authStorage';

interface SessionState {
  driver: DriverProfile | null;
  isOnline: boolean;
  /** True while the persisted session is being restored on boot. */
  restoring: boolean;
  signIn: (driver: DriverProfile, token: string) => Promise<void>;
  signOut: () => Promise<void>;
  setOnline: (value: boolean) => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [driver, setDriver] = useState<DriverProfile | null>(null);
  const [isOnline, setIsOnline] = useState(true);
  const [restoring, setRestoring] = useState(true);

  // Restore a persisted session on boot so the driver stays signed in.
  useEffect(() => {
    let alive = true;
    (async () => {
      const session = await loadSession();
      if (alive && session) {
        setAuthToken(session.token);
        setDriver(session.driver);
        setIsOnline(session.driver.isAvailable);
      }
      if (alive) setRestoring(false);
    })();
    return () => {
      alive = false;
    };
  }, []);

  const signIn = useCallback(async (next: DriverProfile, token: string) => {
    setAuthToken(token);
    setDriver(next);
    setIsOnline(next.isAvailable);
    await persistSession({ token, driver: next });
  }, []);

  const signOut = useCallback(async () => {
    setAuthToken(null);
    setDriver(null);
    setIsOnline(false);
    await clearSession();
  }, []);

  // Optimistic toggle, reconciled with (or reverted by) the API response.
  const setOnline = useCallback(async (value: boolean) => {
    setIsOnline(value);
    try {
      const res = await driverApi.setAvailability(value);
      setIsOnline(res.isAvailable);
    } catch {
      setIsOnline(!value); // revert on failure
    }
  }, []);

  const value = useMemo(
    () => ({ driver, isOnline, restoring, signIn, signOut, setOnline }),
    [driver, isOnline, restoring, signIn, signOut, setOnline],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used within SessionProvider');
  return ctx;
}
