import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { Watchlist } from '@/api/watchlist'
import { FIELDS, instrumentKey, type ScanRow, type ScreenDefinition } from './model'
import { chartTargetUrl } from './chartTarget'
const columns = [
  ['symbol', 'Symbol'],
  ['exchange', 'Exchange'],
  ['close', 'Close'],
  ['session_change', 'Session change'],
  ['session_change_pct', 'Session %'],
  ['bar_change_pct', 'Bar %'],
  ['rsi', 'RSI'],
  ['relative_volume', 'Relative volume'],
  ['direction', 'Setup intent'],
  ['freshness', 'Data state'],
  ['reason', 'Explanation'],
  ['source', 'Source'],
  ['time', 'Completed candle'],
  ['observedAt', 'Source observed'],
  ...FIELDS.filter(
    ([key]) =>
      !['close', 'session_change_pct', 'bar_change_pct', 'rsi', 'relative_volume'].includes(key)
  ),
] as const
const value = (row: ScanRow, key: string): string | number | null => {
  if (key === 'freshness') return row.fresh ? 'Fresh snapshot' : 'Stale snapshot'
  if (key === 'session_change') {
    const close = row.values.close,
      percent = row.values.session_change_pct
    // The engine supplies percent only when the verified prior Daily close exists.
    return typeof close === 'number' && typeof percent === 'number' && percent > -100
      ? (close * percent) / (100 + percent)
      : null
  }
  return key in row
    ? (row as unknown as Record<string, string | number | null>)[key]
    : (row.values[key as keyof typeof row.values] ?? null)
}
export const csvRows = (rows: ScanRow[], keys: readonly string[]) =>
  [keys, ...rows.map((r) => keys.map((k) => value(r, k) ?? ''))]
    .map((cells) => cells.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
    .join('\r\n')
const format = (v: string | number | null, key: string) =>
  v === null
    ? '—'
    : typeof v === 'number'
      ? ['time', 'observedAt'].includes(key)
        ? new Date(v * 1000).toLocaleString()
        : `${key.includes('change') && v > 0 ? '+' : ''}${v.toLocaleString(undefined, { maximumFractionDigits: 6 })}`
      : v
export function ResultsTable({
  rows,
  definition,
  watchlists,
  onAdd,
}: {
  rows: ScanRow[]
  definition: ScreenDefinition
  watchlists: Watchlist[]
  onAdd: (id: number, items: ScanRow[]) => void | Promise<void>
}) {
  const [search, setSearch] = useState(''),
    [sort, setSort] = useState('symbol'),
    [asc, setAsc] = useState(true),
    [page, setPage] = useState(0),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [list, setList] = useState('')
  const [visible, setVisible] = useState<string[]>(columns.slice(0, 14).map((c) => c[0]))
  const matches = useMemo(
    () =>
      rows
        .filter((r) => r.state === 'match')
        .filter((r) => `${r.symbol} ${r.exchange}`.toLowerCase().includes(search.toLowerCase()))
        .sort((a, b) => {
          const x = value(a, sort),
            y = value(b, sort)
          if (x === null && y === null) return instrumentKey(a).localeCompare(instrumentKey(b))
          if (x === null) return 1
          if (y === null) return -1
          return (
            (typeof x === 'number' && typeof y === 'number'
              ? x - y
              : String(x).localeCompare(String(y))) * (asc ? 1 : -1) ||
            instrumentKey(a).localeCompare(instrumentKey(b))
          )
        }),
    [rows, search, sort, asc]
  )
  const pages = Math.max(1, Math.ceil(matches.length / 25)),
    current = Math.min(page, pages - 1),
    selectedRows = rows.filter((r) => r.state === 'match' && selected.has(instrumentKey(r)))
  return (
    <section className="space-y-3" aria-label="Scan results">
      <div className="flex flex-wrap items-center gap-2">
        <strong>{matches.length} matching</strong>
        <input
          className="rounded-md border bg-background px-3 py-2 text-sm"
          aria-label="Search results"
          placeholder="Search symbol or exchange"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(0)
          }}
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            const blob = new Blob(['\ufeff' + csvRows(matches, visible)], {
                type: 'text/csv;charset=utf-8',
              }),
              url = URL.createObjectURL(blob),
              a = document.createElement('a')
            a.href = url
            a.download = 'screener.csv'
            a.click()
            URL.revokeObjectURL(url)
          }}
        >
          Export CSV
        </Button>
        <details>
          <summary className="cursor-pointer text-sm">Columns</summary>
          <div className="absolute z-10 grid max-h-72 overflow-auto rounded-md border bg-popover p-3 shadow-md">
            {columns.map(([key, label]) => (
              <label key={key} className="text-sm">
                <input
                  type="checkbox"
                  checked={visible.includes(key)}
                  onChange={(e) =>
                    setVisible(
                      e.target.checked ? [...visible, key] : visible.filter((v) => v !== key)
                    )
                  }
                />{' '}
                {label}
              </label>
            ))}
          </div>
        </details>
        <select
          className="rounded-md border bg-background p-2 text-sm"
          aria-label="Destination watchlist"
          value={list}
          onChange={(e) => setList(e.target.value)}
        >
          <option value="">Choose watchlist</option>
          {watchlists.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          disabled={!list || !selectedRows.length}
          onClick={() => onAdd(Number(list), selectedRows)}
        >
          Add selected ({selectedRows.length})
        </Button>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="p-2">Select</th>
              {columns
                .filter(([k]) => visible.includes(k))
                .map(([key, label]) => (
                  <th
                    key={key}
                    className="whitespace-nowrap p-2"
                    aria-sort={sort === key ? (asc ? 'ascending' : 'descending') : 'none'}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        setSort(key)
                        setAsc(sort === key ? !asc : true)
                      }}
                    >
                      {label}
                      {sort === key ? (asc ? ' ↑' : ' ↓') : ''}
                    </button>
                  </th>
                ))}
              <th className="p-2">Chart</th>
            </tr>
          </thead>
          <tbody>
            {matches.slice(current * 25, current * 25 + 25).map((row) => (
              <tr key={instrumentKey(row)} className="border-t">
                <td className="p-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.symbol}`}
                    checked={selected.has(instrumentKey(row))}
                    onChange={(e) =>
                      setSelected((old) => {
                        const next = new Set(old)
                        if (e.target.checked) next.add(instrumentKey(row))
                        else next.delete(instrumentKey(row))
                        return next
                      })
                    }
                  />
                </td>
                {columns
                  .filter(([k]) => visible.includes(k))
                  .map(([key]) => {
                    const v = value(row, key)
                    return (
                      <td
                        key={key}
                        className={`max-w-80 p-2 ${key.includes('change') && typeof v === 'number' ? (v > 0 ? 'text-green-600' : v < 0 ? 'text-red-600' : '') : ''}`}
                      >
                        {format(v, key)}
                      </td>
                    )
                  })}
                <td className="whitespace-nowrap p-2">
                  <a
                    className="text-primary underline"
                    href={chartTargetUrl(row, definition, row.pattern)}
                  >
                    Open chart
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!matches.length && (
          <p className="p-6 text-center text-muted-foreground">
            No confirmed matches in this snapshot.
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <Button
          size="sm"
          variant="outline"
          disabled={current === 0}
          onClick={() => setPage(current - 1)}
        >
          Previous
        </Button>
        <span className="text-sm">
          Page {current + 1} of {pages}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={current + 1 >= pages}
          onClick={() => setPage(current + 1)}
        >
          Next
        </Button>
      </div>
    </section>
  )
}
