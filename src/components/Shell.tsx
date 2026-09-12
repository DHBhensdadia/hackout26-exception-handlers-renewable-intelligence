import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/** Scroll to top on route change. */
export function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [pathname]);
  return null;
}

/**
 * Adds `.in` to elements with `.reveal` once they enter the viewport,
 * mirroring the reference site's scroll-reveal behaviour. Also handles
 * the scroll-pinned floating nav pill.
 */
export function useScrollBehaviour() {
  useEffect(() => {
    const reveals = document.querySelectorAll<HTMLElement>(".reveal");
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              e.target.classList.add("in");
              io.unobserve(e.target);
            }
          });
        },
        { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
      );
      reveals.forEach((el) => io.observe(el));
      return () => io.disconnect();
    }
    reveals.forEach((el) => el.classList.add("in"));
  }, []);
}