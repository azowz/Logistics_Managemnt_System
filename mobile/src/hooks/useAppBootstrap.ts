import { useEffect, useState } from 'react';
import { I18nManager } from 'react-native';
import {
  useFonts,
  Tajawal_400Regular,
  Tajawal_500Medium,
  Tajawal_700Bold,
  Tajawal_800ExtraBold,
} from '@expo-google-fonts/tajawal';

/**
 * Forces RTL once at startup and loads the Arabic font family.
 *
 * NOTE: I18nManager.forceRTL only fully applies after a native reload. We call
 * it as early as possible; on first launch in a bare build the layout flips on
 * the following start. In Expo Go / a managed dev client it applies immediately.
 */
export function useAppBootstrap(): { ready: boolean } {
  const [rtlReady, setRtlReady] = useState(false);

  const [fontsLoaded, fontError] = useFonts({
    Tajawal_400Regular,
    Tajawal_500Medium,
    Tajawal_700Bold,
    Tajawal_800ExtraBold,
  });

  useEffect(() => {
    if (!I18nManager.isRTL) {
      I18nManager.allowRTL(true);
      I18nManager.forceRTL(true);
    }
    setRtlReady(true);
  }, []);

  // Don't block the whole app if Google Fonts can't be fetched — fall back to
  // the system font, which still renders Arabic correctly.
  return { ready: rtlReady && (fontsLoaded || !!fontError) };
}
