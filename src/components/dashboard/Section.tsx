import type { ReactNode } from "react";
import { DashedLine } from "../ui/DashedLine";

/**
 * Dashboard section — numbered mono marker, title, optional right meta, and a
 * dashed rule under the head. Sections are ruled bands, not rounded cards.
 */
export function Section({
  id,
  index,
  title,
  meta,
  titleAs,
  children,
}: {
  id: string;
  index: string;
  title: string;
  meta?: ReactNode;
  titleAs?: "h1" | "h2";
  children: ReactNode;
}) {
  const Title = titleAs ?? "h2";
  return (
    <section className="dsection" id={id} aria-labelledby={`${id}-title`}>
      <header className="dsection__head">
        <span className="dsection__idx">§{index}</span>
        <Title className="dsection__title" id={`${id}-title`}>
          {title}
        </Title>
        {meta && <span className="dsection__meta">{meta}</span>}
      </header>
      <DashedLine className="dsection__rule" />
      <div className="dsection__body">{children}</div>
    </section>
  );
}
