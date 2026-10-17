// A status shown as words, with colour only as a help (never colour alone).

const TONE: Record<string, "bad" | "warn" | "ok" | "neutral"> = {
  out_of_stock: "bad",
  at_risk: "bad",
  high: "bad",
  overdue: "bad",
  watch: "warn",
  medium: "warn",
  excess: "warn",
  ok: "ok",
  good: "ok",
  low: "ok",
  received: "ok",
};

export function Badge({ value }: { value: string }) {
  const tone = TONE[value] ?? "neutral";
  return <span className={`status status-${tone}`}>{value.replaceAll("_", " ")}</span>;
}
