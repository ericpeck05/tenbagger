import type { ReactNode } from "react";

type Props = {
  number: number;
  title: string;
  id?: string;
  note?: ReactNode; // shown after the title, left side
  right?: ReactNode;
  className?: string;
  bodyClass?: string;
  children: ReactNode;
};

/** A numbered panel with an uppercase monospace title bar. */
export function Panel({ number, title, id, note, right, className, bodyClass, children }: Props) {
  return (
    <section id={id} className={className ? `panel ${className}` : "panel"}>
      <div className="panel-bar">
        <div className="panel-bar-left">
          <span aria-hidden="true" className="panel-num">
            {number}
          </span>
          <h2 className="panel-title">{title}</h2>
          {note}
        </div>
        {right}
      </div>
      <div className={bodyClass ? `panel-body ${bodyClass}` : "panel-body"}>{children}</div>
    </section>
  );
}
