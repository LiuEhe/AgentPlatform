/** Date-only arithmetic uses UTC so local timezone/DST cannot shift a birthday. */
export function createProfileDate(year: number, month: number, day: number): Date {
  const date = new Date(0)
  date.setUTCFullYear(year, month - 1, day)
  return date
}

export function formatProfileDate(date: Date): string {
  return [String(date.getUTCFullYear()).padStart(4, '0'), String(date.getUTCMonth() + 1).padStart(2, '0'), String(date.getUTCDate()).padStart(2, '0')].join('-')
}

export function parseProfileDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const [year, month, day] = value.split('-').map(Number) as [number, number, number]
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31) return null
  const date = createProfileDate(year, month, day)
  return formatProfileDate(date) === value ? date : null
}
