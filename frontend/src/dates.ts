// Absolute dates are shown in RFC 3339, in the browser's time zone: 2026-10-11T16:47:43+02:00.

const pad = (n: number) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
const ZONED = /([zZ]|[+-]\d{2}:?\d{2})$/;

/** RFC 3339 date-time in local time with its offset. A timestamp without a zone (the agents report some in their
 *  own local time) is shown as written, seconds included, since its offset is unknown. */
export function rfc3339(value: string | number | Date | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" && !ZONED.test(value.trim())) {
    const m = value.trim().match(/^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?/);
    if (m) return m[2] ? `${m[1]}T${m[2].length === 5 ? `${m[2]}:00` : m[2]}` : m[1];
  }
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:`
    + `${pad(d.getSeconds())}${sign}${pad(offset / 60)}:${pad(offset % 60)}`;
}

/** RFC 3339 full-date (YYYY-MM-DD), for values that carry no meaningful time. */
export function rfc3339Date(value: string | null | undefined): string {
  const full = rfc3339(value);
  return full.slice(0, 10);
}
