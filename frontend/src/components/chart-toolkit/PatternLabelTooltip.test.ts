import { expect, it } from 'vitest'
import { PatternLabelTooltip } from './PatternLabelTooltip'
import { patternExplanation } from './patternExplanation'

it('explains the actual pattern and follows its detected direction', () => {
  expect(patternExplanation('Engulfing confirmed at supply', 'PUT')).toMatch(
    /previous candle.*body/i
  )
  expect(patternExplanation('Engulfing confirmed at supply', 'PUT')).toContain('Price may fall')
  expect(patternExplanation('Symmetrical Triangle', 'CALL')).toContain('Price may rise')
  expect(patternExplanation('Doji', 'NEUTRAL')).toContain('No clear direction')
  expect(patternExplanation('Inverted Hammer confirmed', 'CALL')).toMatch(/upper wick/i)
})

it('shows readable text only over the label, hides on update and removes listeners on disposal', () => {
  const root = document.createElement('div')
  document.body.append(root)
  const tooltip = new PatternLabelTooltip(root)
  tooltip.setRegions([
    { left: 10, right: 90, top: 20, bottom: 36, text: 'Hammer: price may rise.' },
  ])
  root.dispatchEvent(new MouseEvent('pointermove', { clientX: 25, clientY: 25 }))
  const popup = document.querySelector('[role="tooltip"]') as HTMLElement
  expect(popup?.textContent).toBe('Hammer: price may rise.')
  expect(popup?.style.display).not.toBe('none')
  root.dispatchEvent(new MouseEvent('pointermove', { clientX: 25, clientY: 80 }))
  expect(popup.style.display).toBe('none')
  root.dispatchEvent(new MouseEvent('pointermove', { clientX: 25, clientY: 25 }))
  tooltip.setRegions([])
  expect(popup.style.display).toBe('none')
  tooltip.dispose()
  expect(document.querySelector('[role="tooltip"]')).toBeNull()
  root.dispatchEvent(new MouseEvent('pointermove', { clientX: 25, clientY: 25 }))
  expect(document.querySelector('[role="tooltip"]')).toBeNull()
  root.remove()
})
