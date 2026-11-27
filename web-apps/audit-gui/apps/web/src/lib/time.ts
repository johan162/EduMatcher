/**
 * Receipt timestamps as the reviewer reads them: UTC, millisecond, with the
 * zone written out. pm-audit stamps every record in UTC; the venue timezone
 * comes with the time controls of a later release.
 */
export function receiptTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.toISOString().replace("T", " ").replace("Z", "")} UTC`;
}
