import { useEffect, useRef, useState } from 'react';

/**
 * Simple 1s-tick countdown from `seconds` to 0.
 * Returns the remaining value and a `reset` helper. Calls `onComplete` once.
 */
export function useCountdown(seconds: number, onComplete?: () => void) {
  const [remaining, setRemaining] = useState(seconds);
  const completed = useRef(false);

  useEffect(() => {
    if (remaining <= 0) {
      if (!completed.current) {
        completed.current = true;
        onComplete?.();
      }
      return;
    }
    const id = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(id);
  }, [remaining, onComplete]);

  const reset = (next: number = seconds) => {
    completed.current = false;
    setRemaining(next);
  };

  return { remaining, reset };
}
