import {render,screen,fireEvent,act} from '@testing-library/react'
import {it,expect,vi,beforeEach} from 'vitest'
import {PremiumPriceAlerts} from './PremiumPriceAlerts'
const sound=vi.hoisted(()=>({readySound:vi.fn(),playAlertSound:vi.fn(()=>true)}))
vi.mock('@/lib/trading/alertDelivery',()=>sound)
beforeEach(()=>{localStorage.clear();vi.clearAllMocks()})
it('arms a frozen support level and repeats on fresh touches, with reset and replay protection',()=>{
 const now=Date.now();vi.spyOn(Date,'now').mockReturnValue(now)
 const props={scope:'user:live:NFO:TESTCE',symbol:'TESTCE',live:true,quote:{price:105,time:now},levels:{support:100,resistance:120,entry:110}}
 const v=render(<PremiumPriceAlerts {...props}/>);
 fireEvent.click(screen.getByText(/Price alerts/));
 fireEvent.click(screen.getByRole('button',{name:'Add alert'}));
 fireEvent.click(screen.getByRole('button',{name:'Enable sound alerts'}));
 expect(sound.readySound).toHaveBeenCalled();
 act(()=>v.rerender(<PremiumPriceAlerts {...props} levels={{...props.levels,support:99}} quote={{price:100,time:now+1000}}/>));
 expect(sound.playAlertSound).toHaveBeenCalledTimes(1);
 expect(screen.getByRole('status')).toHaveTextContent('Support');
 act(()=>v.rerender(<PremiumPriceAlerts {...props} quote={{price:101,time:now+1500}}/>));
 expect(sound.playAlertSound).toHaveBeenCalledTimes(1);
 act(()=>v.rerender(<PremiumPriceAlerts {...props} quote={{price:100,time:now+1700}}/>));
 expect(sound.playAlertSound).toHaveBeenCalledTimes(2);
 expect(sound.playAlertSound).toHaveBeenLastCalledWith({volume:0.7,repeats:3});
 expect(screen.getByText(/1 armed/)).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Reset Support alert'}));
 act(()=>v.rerender(<PremiumPriceAlerts {...props} live={false} quote={{price:99,time:now+1800}}/>));
 expect(sound.playAlertSound).toHaveBeenCalledTimes(2);
 v.unmount();render(<PremiumPriceAlerts {...props}/>);
 expect(screen.getByRole('button',{name:'Enable sound alerts'})).toBeInTheDocument();
 vi.restoreAllMocks()
})
it('prefills the named levels and accepts a custom premium price',()=>{
 const now=Date.now();vi.spyOn(Date,'now').mockReturnValue(now)
 const props={scope:'user:live:NFO:CUSTOMCE',symbol:'CUSTOMCE',live:true,quote:{price:105,time:now},levels:{support:100,resistance:120,entry:110}}
 const v=render(<PremiumPriceAlerts {...props}/>);
 fireEvent.click(screen.getByText(/Price alerts/));
 const source=screen.getByLabelText('Alert level source'), price=screen.getByLabelText('Alert premium price');
 fireEvent.change(source,{target:{value:'resistance'}});expect(price).toHaveValue(120);
 fireEvent.change(source,{target:{value:'entry'}});expect(price).toHaveValue(110);
 fireEvent.change(source,{target:{value:'custom'}});expect(screen.getByRole('button',{name:'Add alert'})).toBeDisabled();
 fireEvent.change(price,{target:{value:'112.5'}});fireEvent.click(screen.getByRole('button',{name:'Add alert'}));
 act(()=>v.rerender(<PremiumPriceAlerts {...props} quote={{price:113,time:now+500}}/>));
 expect(sound.playAlertSound).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Enable sound alerts'}));
 act(()=>v.rerender(<PremiumPriceAlerts {...props} quote={{price:112,time:now+1000}}/>));
 expect(sound.playAlertSound).toHaveBeenCalledOnce();
 expect(screen.getByRole('status')).toHaveTextContent('Custom level ₹112.50');
 vi.restoreAllMocks()
})

it('keeps a previously reached saved alert armed for repeated hits',()=>{
 const now=Date.now();vi.spyOn(Date,'now').mockReturnValue(now)
 const scope='user:live:NFO:SAVEDPE'
 localStorage.setItem(`chart.premium-alerts.v1:${scope}`,JSON.stringify([{id:'saved',label:'Entry',price:100,enabled:true,fired:true}]))
 const props={scope,symbol:'SAVEDPE',live:true,quote:{price:105,time:now},levels:{support:null,resistance:null,entry:null}}
 const v=render(<PremiumPriceAlerts {...props}/>);
 fireEvent.click(screen.getByText(/Price alerts/));
 expect(screen.getByText(/1 armed/)).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Enable sound alerts'}));
 act(()=>v.rerender(<PremiumPriceAlerts {...props} quote={{price:100,time:now+1000}}/>));
 expect(sound.playAlertSound).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByRole('button',{name:'Test sound'}));
 expect(sound.playAlertSound).toHaveBeenLastCalledWith({volume:0.7,repeats:3});
 vi.restoreAllMocks()
})
