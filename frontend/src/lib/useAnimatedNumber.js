'use client';

import { useEffect, useRef, useState } from 'react';
import { animate } from 'framer-motion';

/**
 * useAnimatedNumber — tween a value to its new target so live numbers glide
 * across the 2s data flush instead of snapping. Honors reduced motion.
 */
export function useAnimatedNumber(value, duration = 0.7) {
  const [display, setDisplay] = useState(value);
  const from = useRef(value);

  useEffect(() => {
    const reduce = typeof window !== 'undefined'
      && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { from.current = value; setDisplay(value); return; }

    const controls = animate(from.current, value, {
      duration,
      ease: [0.4, 0, 0.2, 1],
      onUpdate: (v) => { from.current = v; setDisplay(v); },
    });
    return () => controls.stop();
  }, [value, duration]);

  return display;
}
