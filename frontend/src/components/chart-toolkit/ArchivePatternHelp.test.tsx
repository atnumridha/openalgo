import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ArchivePatternHelp } from './ArchivePatternHelp'

it('shows the 15-pattern crypto reference only for a crypto chart', () => {
  const view = render(<ArchivePatternHelp crypto />)
  expect(screen.getByText('Crypto chart patterns · 15 active')).toBeInTheDocument()
  expect(screen.getByText('Cup and Handle')).toBeInTheDocument()
  view.rerender(<ArchivePatternHelp />)
  expect(screen.queryByText('Crypto chart patterns · 15 active')).not.toBeInTheDocument()
})

it('shows the verified cheat-sheet additions once and keeps them out of noncrypto help', () => {
  const view = render(<ArchivePatternHelp crypto />)
  expect(screen.getByText('TradingView cheat sheet · 20 covered')).toBeInTheDocument()
  for (const name of ['Gartley', 'Cypher', 'Livermore Cylinder', 'Megaphone', 'Cup and Handle'])
    expect(screen.getAllByText(name)).toHaveLength(1)
  expect(screen.getByRole('link', { name: 'TradingView cheat sheet' })).toHaveAttribute(
    'href',
    'https://www.tradingview.com/chart/BTCUSDT/6puZ59qW-TOP-20-Key-Patterns-cheat-sheet/'
  )
  view.rerender(<ArchivePatternHelp />)
  expect(screen.queryByText('TradingView cheat sheet · 20 covered')).not.toBeInTheDocument()
})
