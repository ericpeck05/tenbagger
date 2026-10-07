/** The numbered panels on the stock page. Pressing the number key jumps to the panel. */
export const PANELS = [
  { n: 1, id: "price", label: "Price" },
  { n: 2, id: "lynch", label: "Lynch" },
  { n: 3, id: "valuation", label: "Valuation" },
  { n: 4, id: "growth", label: "Growth" },
  { n: 5, id: "quality", label: "Quality" },
  { n: 6, id: "balance", label: "Balance" },
  { n: 7, id: "trend", label: "Trend" },
  { n: 8, id: "filings", label: "Filings" },
] as const;

export function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
