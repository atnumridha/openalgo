import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { DailyDiscipline } from './DailyDiscipline'
const now = Date.now() / 1000
const date = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date(now * 1000))
const discipline = {
  date,
  entries: 1,
  max_entries: 3,
  remaining_entries: 2,
  excess_entries: 0,
  profit_target: 2000,
  loss_limit: 1000,
  profit_reached: false,
  loss_reached: false,
  net: 100,
  updated_at: now,
}
const props = { scope: 'u:live', discipline, bookTime: now, now }
beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
})
it('shows entries used and remaining, alerts green at the exact profit boundary', () => {
  const view = render(<DailyDiscipline {...props} />)
  expect(screen.getByLabelText('Daily entry count')).toHaveTextContent('1 / 3')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  view.rerender(
    <DailyDiscipline
      {...props}
      discipline={{ ...discipline, net: 2000, profit_reached: true, profit_reached_at: now }}
    />
  )
  expect(screen.getByRole('alert')).toHaveAttribute('data-tone', 'profit')
  expect(
    within(screen.getByRole('alert')).getByText(/Profit milestone reached/)
  ).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('2 entries remaining')
  expect(screen.queryByText(/Stop trading for today/)).not.toBeInTheDocument()
})

it.each([0, 1, 2])('allows further profit after the milestone with %i entries used', (entries) => {
  render(
    <DailyDiscipline
      {...props}
      discipline={{ ...discipline, entries, profit_reached: true, net: 2500 }}
    />
  )
  const alert = screen.getByRole('alert')
  expect(alert).toHaveAttribute('data-tone', 'profit')
  expect(alert).toHaveTextContent(
    `You may continue with ${3 - entries} ${entries === 2 ? 'entry' : 'entries'} remaining`
  )
  expect(alert).not.toHaveTextContent('Stop trading for today')
})

it.each([3, 4])('stops encouraging more profit once %i entries are used', (entries) => {
  render(
    <DailyDiscipline
      {...props}
      discipline={{ ...discipline, entries, profit_reached: true, net: 2500 }}
    />
  )
  expect(screen.getByRole('alert')).toHaveTextContent('Stop trading for today')
  expect(screen.getByRole('alert')).not.toHaveTextContent('You may continue')
  expect(screen.getByRole('alert')).not.toHaveAttribute('data-tone', 'profit')
})

it('keeps the loss warning above the profit milestone even with entries remaining', () => {
  render(
    <DailyDiscipline
      {...props}
      discipline={{ ...discipline, profit_reached: true, loss_reached: true, net: -1000 }}
    />
  )
  expect(screen.getByRole('alert')).toHaveAttribute('data-tone', 'loss')
  expect(screen.getByRole('alert')).toHaveTextContent('Stop trading for today')
  expect(screen.getByRole('alert')).not.toHaveTextContent('You may continue')
})

it('does not offer more entries until the daily count is verified', () => {
  render(
    <DailyDiscipline
      {...props}
      discipline={{ ...discipline, profit_reached: true, net: 2500, count_verified: false }}
    />
  )
  expect(screen.getByRole('alert')).toHaveTextContent('Entry count needs verification')
  expect(screen.getByRole('alert')).not.toHaveTextContent('You may continue')
})
it('prioritizes red loss and excessive entries, snoozes for two minutes and preserves it on reload', () => {
  const d = {
    ...discipline,
    net: -1000,
    loss_reached: true,
    loss_reached_at: now,
    entries: 4,
    remaining_entries: 0,
    excess_entries: 1,
  }
  let view = render(<DailyDiscipline {...props} discipline={d} />)
  expect(screen.getByRole('alert')).toHaveAttribute('data-tone', 'loss')
  expect(screen.getByLabelText('Daily entry count')).toHaveTextContent('4 / 3')
  expect(screen.getByRole('alert')).toHaveTextContent('1 extra entry')
  fireEvent.click(screen.getByRole('button', { name: 'Close warning' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  view.unmount()
  view = render(<DailyDiscipline {...props} now={now + 30} bookTime={now + 30} discipline={d} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  view.rerender(
    <DailyDiscipline
      {...props}
      now={now + 121}
      bookTime={now + 121}
      discipline={{ ...d, updated_at: now + 121 }}
    />
  )
  expect(screen.getByRole('alert')).toHaveAttribute('data-tone', 'loss')
})
it('does not flash on stale data, old sessions or replayed chart values', () => {
  const d = { ...discipline, entries: 3, remaining_entries: 0, net: 2001, profit_reached: true }
  const view = render(<DailyDiscipline {...props} bookTime={now - 20} discipline={d} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText(/Waiting for fresh account data/)).toBeInTheDocument()
  view.rerender(<DailyDiscipline {...props} discipline={{ ...d, date: '2000-01-01' }} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
it('re-alerts on another outside entry during snooze and resets the next day', () => {
  const d = { ...discipline, entries: 3, remaining_entries: 0 }
  const view = render(<DailyDiscipline {...props} discipline={d} />)
  fireEvent.click(screen.getByRole('button', { name: 'Close warning' }))
  view.rerender(<DailyDiscipline {...props} discipline={{ ...d, entries: 4, excess_entries: 1 }} />)
  expect(screen.getByRole('alert')).toBeInTheDocument()
  view.rerender(<DailyDiscipline {...props} discipline={{ ...discipline, date: '2000-01-01' }} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('does not describe an old discipline value as fresh because the book timestamp refreshed', () => {
  render(
    <DailyDiscipline
      {...props}
      discipline={{ ...discipline, net: -1100, loss_reached: true, updated_at: now - 60 }}
    />
  )
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText(/Waiting for fresh account data/)).toBeInTheDocument()
})

it('covers the screen without a modal input blocker and keeps exit controls usable', () => {
  render(
    <>
      <DailyDiscipline {...props} discipline={{ ...discipline, entries: 3 }} />
      <button>Exit existing trade</button>
    </>
  )
  expect(screen.getByRole('alert')).toHaveClass('fixed', 'inset-0', 'pointer-events-none')
  expect(screen.getByRole('alert')).not.toHaveAttribute('aria-modal', 'true')
  expect(screen.getByRole('button', { name: 'Exit existing trade' })).toBeEnabled()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('persists a configurable warning interval and reschedules a snoozed warning', () => {
  const d = { ...discipline, entries: 3 }
  let view = render(<DailyDiscipline {...props} discipline={d} />)
  expect(screen.getByLabelText('Warning repeat interval')).toHaveValue('120')
  fireEvent.change(screen.getByLabelText('Warning repeat interval'), { target: { value: '300' } })
  fireEvent.click(screen.getByRole('button', { name: 'Close warning' }))
  view.unmount()
  view = render(
    <DailyDiscipline
      {...props}
      discipline={{ ...d, updated_at: now + 121 }}
      now={now + 121}
      bookTime={now + 121}
    />
  )
  expect(screen.getByLabelText('Warning repeat interval')).toHaveValue('300')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Warning repeat interval'), { target: { value: '30' } })
  view.rerender(
    <DailyDiscipline
      {...props}
      discipline={{ ...d, updated_at: now + 152 }}
      now={now + 152}
      bookTime={now + 152}
    />
  )
  expect(screen.getByRole('alert')).toBeInTheDocument()
})

it('takes me to open trades after hiding the warning without placing an exit order', () => {
  const exit = vi.fn()
  render(
    <>
      <DailyDiscipline {...props} discipline={{ ...discipline, entries: 3 }} />
      <h3 tabIndex={-1} id="kotak-open-trades">
        Open trades & live monitoring
      </h3>
      <button onClick={exit}>Exit existing trade</button>
    </>
  )
  fireEvent.click(screen.getByRole('button', { name: 'Go to open trades' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Open trades & live monitoring' })).toHaveFocus()
  expect(exit).not.toHaveBeenCalled()
})

it('leaves Escape to the rest of the page while the warning is closed', () => {
  render(<DailyDiscipline {...props} discipline={{ ...discipline, entries: 3 }} />)
  fireEvent.click(screen.getByRole('button', { name: 'Close warning' }))
  const escape = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
  document.dispatchEvent(escape)
  expect(escape.defaultPrevented).toBe(false)
})

it('preserves warning control focus when changing the interval or repeating the flash', () => {
  const d = { ...discipline, entries: 3 }
  const view = render(<DailyDiscipline {...props} discipline={d} />)
  const interval = screen.getByLabelText('Alert repeat interval')
  interval.focus()
  fireEvent.change(interval, { target: { value: '30' } })
  expect(screen.getByLabelText('Alert repeat interval')).toHaveFocus()
  const close = screen.getByRole('button', { name: 'Close warning' })
  close.focus()
  view.rerender(
    <DailyDiscipline
      {...props}
      discipline={{ ...d, updated_at: now + 31 }}
      bookTime={now + 31}
      now={now + 31}
    />
  )
  expect(screen.getByRole('button', { name: 'Close warning' })).toHaveFocus()
})
