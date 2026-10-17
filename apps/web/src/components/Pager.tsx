// "Rows 51-100 of 800" with Previous / Next buttons.

const numbers = new Intl.NumberFormat("en-GB");

export function Pager({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total === 0) return null;
  const last = Math.min(offset + limit, total);
  return (
    <nav className="pager" aria-label="Pages">
      <button type="button" className="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - limit, 0))}>
        Previous
      </button>
      <span>
        Rows {numbers.format(offset + 1)}–{numbers.format(last)} of {numbers.format(total)}
      </span>
      <button type="button" className="secondary" disabled={last >= total} onClick={() => onChange(offset + limit)}>
        Next
      </button>
    </nav>
  );
}
