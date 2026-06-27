export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 1) {
    return '0 B'
  }

  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0

  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }

  const rounded = value >= 10 ? value.toFixed(0) : value.toFixed(1)
  return `${rounded} ${units[index]}`
}
