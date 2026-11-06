import { webClient } from '@/api/client'
export interface OptionRiskRequest {symbol:string;exchange:string;entry:string;stop:string;lots:number;slippage:string;broker?:'kotak'|'flattrade';target?:string;position?:boolean}
export interface OptionRiskEstimate {
  net_at_stop?:string
  broker?:'kotak'|'flattrade'
  symbol:string;exchange:string;quantity:number;lots:number;lot_size:number;tick_size:string
  entry:string;stop:string;target:string;gross_reward_risk:string|null;net_reward_risk:string|null
  net_profit:string;net_loss:string;profit_fees:string;loss_fees:string;slippage:string
  brokerage_per_order:string;fee_date:string;fee_source:string;fee_version:string;estimated:true
  profit_fee_breakdown:Record<string,string>;loss_fee_breakdown:Record<string,string>
}
export const optionRiskApi = {
  preview: async (body:OptionRiskRequest, signal?:AbortSignal):Promise<OptionRiskEstimate> =>
    (await webClient.get('/neodesk/api/chart/risk-preview',{params:body,signal,timeout:10000})).data,
}
