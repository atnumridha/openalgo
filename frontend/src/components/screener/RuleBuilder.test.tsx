import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { RuleBuilder } from './RuleBuilder'
import { validateDefinition } from './engine'
import { makePresets } from './presets'
it('sets the displayed one-percent tolerance when switching to Within %', () => {
  const base = makePresets()[0]
  let current = base
  function Fixture() {
    const [rule, setRule] = useState(base.rule)
    current = { ...base, rule }
    return <RuleBuilder rule={rule} onChange={setRule} />
  }
  render(<Fixture />)
  fireEvent.change(screen.getByLabelText('Comparison'), { target: { value: 'within_pct' } })
  expect(screen.getByLabelText('Tolerance percent')).toHaveValue(1)
  expect(() => validateDefinition(current)).not.toThrow()
})
