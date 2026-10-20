import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarketStructure, OptionLevels } from './PriceLevels'

describe('Clear trading levels', () => {
  it('labels drafts as option premiums, never accepted protection', () => {
    render(<OptionLevels entry={100} sl={90} target={120} autoTarget={false} />)
    expect(screen.getByText('Trade plan · option premium in ₹')).toBeInTheDocument()
    expect(screen.getByText('Stop loss (SL)')).toBeInTheDocument()
    expect(screen.getByText(/Target is a guide/)).toBeInTheDocument()
    expect(screen.queryByText('Broker-confirmed stop loss')).not.toBeInTheDocument()
  })
  it('does not present an unconfirmed stop as protection', () => {
    render(<OptionLevels entry={100} sl={90} target={120} actual protectedStop={false} />)
    expect(screen.getByText('Unconfirmed')).toBeInTheDocument()
    expect(screen.getByText(/Stop protection is not confirmed/)).toBeInTheDocument()
  })
  it('shows nearest confirmed lows below price and highs above as index levels', () => {
    render(
      <MarketStructure
        index="NIFTY"
        price={22600}
        fresh
        zones={[
          { price: 22580, kind: 'low', source: 'Repeated lows', touches: 2 },
          { price: 22500, kind: 'low', source: 'Previous day low', touches: 1 },
          { price: 22640, kind: 'high', source: 'Previous day high', touches: 1 },
          { price: 22590, kind: 'high', source: 'Broken high', touches: 1 },
        ]}
      />
    )
    expect(screen.getByText('22,580.00')).toBeInTheDocument()
    expect(screen.getByText('22,640.00')).toBeInTheDocument()
    expect(screen.queryByText('22,590.00')).not.toBeInTheDocument()
    expect(screen.getByText(/Index points/)).toBeInTheDocument()
  })
  it('keeps missing levels explicit instead of inventing support or resistance', () => {
    render(<MarketStructure index="NIFTY" fresh={false} zones={[]} />)
    expect(screen.getAllByText('Not available')).toHaveLength(2)
    expect(screen.getByText(/Last calculated levels/)).toBeInTheDocument()
  })
})
