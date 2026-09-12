import { useEffect, useRef, useState } from "react";

/**
 * Reusable reveal-on-scroll wrapper. When the element enters the viewport it
 * gets `.in` added (which flips the CSS transitioned `.reveal` state).
 */
export function Reveal({
  children,
  className = "",
  delay = "",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: string;
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  // Fall back to visible immediately when IntersectionObserver is unavailable.
  const [inView, setInView] = useState(() => typeof window !== "undefined" && !("IntersectionObserver" in window));

  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setInView(true);
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      style={style}
      className={`reveal ${delay} ${inView ? "in" : ""} ${className}`.trim()}
    >
      {children}
    </div>
  );
}