import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ChartIndexQuote } from './ChartIndexQuote'
const quote = vi.hoisted(() => ({ useLiveQuote: vi.fn() }))
vi.mock('@/hooks/useLiveQuote', () => quote)
beforeEach(() => { quote.useLiveQuote.mockReset() })
it.each([
  [23120, 23000, '+120.00', '+0.52%', 'dark:text-emerald-400'],
  [22880, 23000, '−120.00', '−0.52%', 'dark:text-red-400'],
  [23000, 23000, '0.00', '0.00%', 'text-muted-foreground'],
])('shows selected index price %s and its signed day movement', (ltp, close, change, percent, tone) => {
  quote.useLiveQuote.mockReturnValue({data:{ltp,close},isLive:true,dataSource:'websocket'})
  render(<ChartIndexQuote symbol="NIFTY" />)
  expect(screen.getByLabelText('Index price')).toHaveTextContent(ltp.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}))
  expect(screen.getByLabelText('Index day change')).toHaveTextContent(`${change} (${percent})`)
  expect(screen.getByLabelText('Index day change')).toHaveClass(tone)
  expect(screen.getByText('Live')).toBeVisible()
})
it('labels delayed quotes and leaves unknown day movement empty', () => {
  quote.useLiveQuote.mockReturnValue({data:{ltp:23120,close:0},isLive:false,dataSource:'rest'})
  render(<ChartIndexQuote symbol="SENSEX" />)
  expect(quote.useLiveQuote).toHaveBeenCalledWith('SENSEX','BSE_INDEX',expect.objectContaining({mode:'Quote',useDepthFallback:false}))
  expect(screen.getByLabelText('Index day change')).toHaveTextContent('—')
  expect(screen.getByText('Last quote')).toBeVisible()
})
it('shows no fake price before data arrives', () => {
  quote.useLiveQuote.mockReturnValue({data:{ltp:NaN},isLive:false,dataSource:'none'})
  render(<ChartIndexQuote symbol="BANKNIFTY" />)
  expect(screen.getByLabelText('Index price')).toHaveTextContent('—')
  expect(screen.getByText('Waiting for quote')).toBeVisible()
})
