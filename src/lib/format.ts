/** "$9,700" for whole dollars, "$99.99" otherwise, as the backend writes amounts. */
export function usd(amount: number): string {
  const whole = Number.isInteger(amount);
  return `$${amount.toLocaleString("en-US", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 })}`;
}

/** "2026-10-09T10:12:00Z" -> "Oct 09, 10:12" in the viewer's time zone. */
export function formatAt(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

/** First 8 and last 6 characters of a hash. */
export const short = (x: string) => `${x.slice(0, 8)}…${x.slice(-6)}`;

/** "Component #063" -> "#063"; anything without a "#" is returned unchanged. */
export const unitShort = (unitRef: string) => unitRef.match(/#\S+$/)?.[0] ?? unitRef;
