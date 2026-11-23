import { useEffect, useRef, useState } from 'react';

/**
 * Simple 1s-tick countdown from `seconds` to 0.
 * Returns the remaining value and a `reset` helper. Calls `onComplete` once.
 */
export function useCountdown(seconds: number | null, onComplete?: () => void, enabled = true) {
  const [remaining, setRemaining] = useState(seconds ?? 0);
  const completed = useRef(false);

  useEffect(() => {
    completed.current = false;
    setRemaining(seconds ?? 0);
  }, [seconds]);

  useEffect(() => {
    if (seconds === null || !enabled) return;
    if (remaining <= 0) {
      if (!completed.current) {
        completed.current = true;
        onComplete?.();
      }
      return;
    }
    const id = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(id);
  }, [remaining, onComplete, seconds, enabled]);

  const reset = (next: number = seconds ?? 0) => {
    completed.current = false;
    setRemaining(next);
  };

  return { remaining, reset };
}
