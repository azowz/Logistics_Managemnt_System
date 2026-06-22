import { Redirect } from 'expo-router';
import { useSession } from '../src/store/session';

/**
 * Entry point. Waits for the persisted session to restore, then routes a
 * signed-in driver straight to the dashboard, otherwise to the login gate.
 */
export default function Index() {
  const { driver, restoring } = useSession();
  if (restoring) return null; // splash stays visible until restore resolves
  return <Redirect href={driver ? '/driver/home' : '/auth/login'} />;
}
