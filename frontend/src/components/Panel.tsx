import type { ReactNode } from "react";

type Props = {
  number: number;
  title: string;
  id?: string;
  right?: ReactNode;
  children: ReactNode;
};

/** A numbered panel with an uppercase monospace title bar. */
export function Panel({ number, title, id, right, children }: Props) {
  return (
    <section id={id} className="panel">
      <div className="panel-bar">
        <div className="panel-bar-left">
          <span aria-hidden="true" className="panel-num">
            {number}
          </span>
          <h2 className="panel-title">{title}</h2>
        </div>
        {right}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}
