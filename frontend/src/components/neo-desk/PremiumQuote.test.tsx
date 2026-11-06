import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { PremiumQuote } from './PremiumQuote'
it.each([
 [110,100,'+₹10.00 (+10.00%)','text-emerald-400'],
 [90,100,'−₹10.00 (−10.00%)','text-red-400'],
 [100,100,'₹0.00 (0.00%)','text-muted-foreground'],
])('shows signed premium movement for %s in a clear color',(price,previousClose,label,tone)=>{
 render(<PremiumQuote price={price} previousClose={previousClose} dark/> )
 expect(screen.getByLabelText('Premium day change')).toHaveTextContent(label)
 expect(screen.getByLabelText('Premium day change')).toHaveClass(tone)
 expect(screen.getByLabelText('Premium price')).toHaveClass(tone)
})
it('does not substitute strike or underlying prices when the option previous close is missing',()=>{
 render(<PremiumQuote price={100} previousClose={0} dark/>)
 expect(screen.getByLabelText('Premium day change')).toHaveTextContent('—')
 expect(screen.getByLabelText('Premium price')).toHaveTextContent('₹100.00')
})
