// Spec 4.B: every screen shows that the operations data is simulated.

export function DataBadge() {
  return (
    <span
      className="badge"
      title="Stock, suppliers and orders are invented by the seed generator (SYN- codes). Demand is borrowed from public M5 forecasts."
    >
      Simulated data
    </span>
  );
}
