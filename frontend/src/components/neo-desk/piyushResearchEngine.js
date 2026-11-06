// Official NSE daily calendar used by the archived research; outside this span,
// adjacent observed weekday sessions are used (chart feed has no holiday calendar).
const RESEARCH_DAYS=[19997,19999,20000,20003,20004,20005,20006,20007,20010,20011,20012,20013,20014,20017,20018,20019,20020,20021,20024,20025,20026,20027,20028,20031,20032,20033,20034,20035,20038,20039,20040,20041,20045,20046,20048,20049,20052,20053,20054,20055,20056,20059,20060,20061,20062,20063,20066,20067,20068,20069,20070,20073,20074,20075,20076,20077,20080,20081,20083,20084,20087,20088,20089,20090,20091,20094,20095,20096,20097,20098,20101,20102,20103,20104,20105,20108,20109,20110,20111,20112,20115,20116,20117,20118,20119,20120,20122,20123,20124,20125,20126,20129,20130,20131,20132,20133,20136,20137,20138,20139,20140,20143,20144,20146,20147,20150,20151,20152,20153,20154,20157,20158,20159,20160,20164,20165,20166,20167,20168,20171,20172,20173,20174,20175,20179,20180,20181,20182,20185,20186,20187,20189,20193,20194,20195,20199,20200,20201,20202,20203,20206,20207,20208,20210,20213,20214,20215,20216,20217,20220,20221,20222,20223,20224,20227,20228,20229,20230,20231,20234,20235,20236,20237,20238,20241,20242,20243,20244,20245,20248,20249,20250,20251,20252,20255,20256,20257,20258,20259,20262,20263,20264,20265,20266,20269,20270,20271,20272,20273,20276,20277,20278,20279,20280,20283,20284,20285,20286,20287,20290,20291,20292,20293,20294,20297,20298,20299,20300,20301,20304,20305,20306,20307,20308,20311,20312,20313,20314,20318,20319,20320,20321,20322,20325,20326,20328,20329,20332,20333,20334,20335,20336,20339,20340,20341,20342,20343,20346,20347,20348,20349,20350,20353,20354,20355,20356,20357,20360,20361,20362,20364,20367,20368,20369,20370,20371,20374,20375,20376,20377,20378,20381,20382,20384,20385,20388,20389,20390,20391,20392,20395,20396,20398,20399,20402,20403,20404,20405,20406,20409,20410,20411,20412,20413,20416,20417,20418,20419,20420,20423,20424,20425,20426,20427,20430,20431,20432,20433,20434,20437,20438,20439,20440,20441,20444,20445,20446,20448,20451,20452,20453,20454,20455,20458,20459,20460,20461,20462,20465,20466,20467,20469,20472,20473,20474,20475,20476,20480,20481,20482,20483,20485,20486,20487,20488,20489,20490,20493,20494,20495,20496,20497,20500,20501,20502,20503,20504,20507,20508,20509,20510,20511,20514,20516,20517,20518,20521,20522,20523,20524,20525,20528,20529,20530,20531,20532,20535,20536,20537,20539,20542,20544,20545,20549,20550,20551,20552,20553,20556,20558,20559,20560,20563,20564,20565,20566,20567,20570,20571,20572,20573,20577,20578,20579,20580,20581,20584,20585,20586,20587,20588,20591,20592,20593,20594,20595,20598,20599,20600,20602,20605,20606,20607,20608,20609,20612,20613,20614,20615,20616,20619,20620,20621,20622,20623,20626,20627,20628,20629,20633,20634,20635,20636,20637,20640,20641,20642,20643,20644,20647,20648,20649,20650,20651,20654,20655];
const SESSION_ORDER=new Map(RESEARCH_DAYS.map((d,i)=>[d,i]));
const adjacent=(a,b)=>SESSION_ORDER.has(a)&&SESSION_ORDER.has(b)?SESSION_ORDER.get(b)-SESSION_ORDER.get(a)===1:b-a<=4;
/** Public-reel research reconstruction. Pure chart study: no network or orders.
 * Requires 1m NIFTY/SENSEX spot bars; 5m signals aggregate complete minutes.
 * Levels reproduce the INDEX diagnostic, not premium stops or option returns.
 */
const MODES = {
  ema_cross_1m: 'EMA 8/33 cross · 1m',
  ema_cross_5m: 'EMA 8/33 cross · 5m',
  ema_pullback_1m: 'EMA 8 pullback · 1m',
  previous_day_break_5m: 'Previous-day breakout · 5m',
  opening_range_break_5m: 'Opening-range breakout · 5m',
};
const KEYS=['fast','slow','upper','lower','entry','stop','target','event','direction','exit','ready'];
const clock=t=>((Math.floor(t/60)+330)%1440+1440)%1440;
const day=t=>Math.floor((t+19800)/86400);
const valid=b=>Number.isFinite(b.time)&&b.time%60===0&&[b.open,b.high,b.low,b.close].every(v=>Number.isFinite(v)&&v>0)&&b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close);
export function compute(bars,settings={},ctx={}) {
  const universal=ctx.universal===true,continuous=universal&&ctx.continuous===true;
  const sessionStart=continuous?0:(ctx.session?.start??555),sessionEnd=continuous?1440:(ctx.session?.end??930),exitClock=sessionEnd-15;
  const clock=t=>((Math.floor(t/60)+(continuous?0:330))%1440+1440)%1440;
  const day=t=>Math.floor((t+(continuous?0:19800))/86400);
  const nearSessions=(a,b)=>{
    if(!universal)return adjacent(a,b);
    if(continuous)return b-a===1;
    if(!Number.isFinite(a))return false;
    let next=a+1;while([0,6].includes(new Date(next*86400000).getUTCDay()))next++;
    return b===next;
  };
  const tick=Number(ctx.tickSize);
  const values=Object.fromEntries(KEYS.map(k=>[k,Array(bars.length).fill(null)]));
  const empty={values,trades:[],status:'Use a 1-minute NIFTY or SENSEX index chart'};
  const symbol=String(ctx.symbol||'').toUpperCase();
  if(ctx.transformed||!['1m','1','1min'].includes(String(ctx.interval))||(!universal&&! /^(?:(?:NSE_INDEX|BSE_INDEX|NSE|BSE):)?(?:NIFTY|NIFTY 50|NIFTY50|SENSEX)(?:-INDEX)?$/.test(symbol)))return empty;
  if(universal&&(!Number.isFinite(tick)||tick<=0||!symbol))return {...empty,status:'Contract price increment unavailable'};
  if(universal&&!continuous&&!ctx.session)return {...empty,status:'Configured exchange session unavailable'};
  values.ready.fill(1);
  const mode=Object.hasOwn(MODES,settings.mode)?settings.mode:'previous_day_break_5m';
  const tf=mode.endsWith('5m')?5:1, reward=universal?2:Number(settings.reward)===4?4:3;
  const groups=[],daily=new Map(),seen=new Map();
  for(const b of bars)seen.set(b.time,(seen.get(b.time)||0)+1);
  let g=null;
  // Last candle is deliberately unconfirmed. Its open can execute a prior signal.
  for(let i=0;i<bars.length-1;i++) {
    const b=bars[i],m=clock(b.time),d=day(b.time),w=new Date((b.time+(continuous?0:19800))*1000).getUTCDay();
    if(!valid(b)||seen.get(b.time)!==1||m<sessionStart||m>=sessionEnd||(!continuous&&(w===0||w===6)))continue;
    let dd=daily.get(d);if(!dd){dd={count:0,start:m,last:b.time,high:b.high,low:b.low,close:b.close,complete:true};daily.set(d,dd)}
    if(dd.count&&b.time!==dd.last+60)dd.complete=false;
    dd.count++;dd.last=b.time;dd.high=Math.max(dd.high,b.high);dd.low=Math.min(dd.low,b.low);dd.close=b.close;
    const key=d*1000+Math.floor((m-sessionStart)/tf);
    if(!g||g.key!==key){g={key,date:d,time:b.time,clock:m,open:b.open,high:b.high,low:b.low,close:b.close,count:0,last:b.time,indices:[],good:true};groups.push(g)}
    if(g.count&&b.time!==g.last+60)g.good=false;
    g.count++;g.last=b.time;g.high=Math.max(g.high,b.high);g.low=Math.min(g.low,b.low);g.close=b.close;g.indices.push(i);
  }
  const ds=[...daily.keys()],prior=new Map(ds.map((d,i)=>[d,nearSessions(ds[i-1],d)?daily.get(ds[i-1]):null]));
  if(universal&&mode==='previous_day_break_5m'&&!((p)=>p&&p.complete&&p.count===sessionEnd-sessionStart&&p.start===sessionStart&&clock(p.last)===sessionEnd-1)(prior.get(day(bars.at(-1)?.time??0)))){
    values.ready.fill(null);return {values,trades:[],status:'Complete previous session candles unavailable; retrying history.'};
  }
  const events=new Map();let last=null,arm=null,n=0,e8=0,e33=0,oh=null,ol=null;
  for(const b of groups) {
    if(!b.good||b.count!==tf||(b.clock-sessionStart)%tf!==0)continue;
    const same=last&&last.date===b.date;
    const overnight=last&&!same&&b.clock===sessionStart&&last.clock===sessionEnd-tf&&nearSessions(last.date,b.date);
    const contiguous=last&&(b.time===last.time+tf*60||overnight);
    if(!contiguous){n=0;arm=null}
    const p8=n>=33?e8:NaN,p33=n>=33?e33:NaN;
    e8=n?e8+(b.close-e8)*2/9:b.close;e33=n?e33+(b.close-e33)*2/34:b.close;n++;
    const up=p8<=p33&&e8>e33,down=p8>=p33&&e8<e33;
    let side=0;
    if(mode.startsWith('ema')) {
      if(up||down){arm={side:up?1:-1,at:b.time,date:b.date};if(mode!=='ema_pullback_1m')side=arm.side}
      else if(mode==='ema_pullback_1m'&&arm){
        const s=arm.side,aligned=s===1?e8>e33:e8<e33;
        if(!contiguous||arm.date!==b.date||b.time-arm.at>900||!aligned)arm=null;
        else if(s===1?b.low<=e8&&b.close>e8&&b.close>b.open:b.high>=e8&&b.close<e8&&b.close<b.open){side=s;arm=null}
      }
    }
    if(!same){oh=null;ol=null}if(b.clock===sessionStart){oh=b.high;ol=b.low}
    const p=prior.get(b.date),complete=p&&p.complete&&p.count===sessionEnd-sessionStart&&p.start===sessionStart&&clock(p.last)===sessionEnd-1;
    const pc=same&&b.time-last.time===tf*60?last.close:b.clock===sessionStart&&p?p.close:NaN;
    let upper=null,lower=null;
    if(mode==='previous_day_break_5m'&&complete){upper=p.high;lower=p.low}
    if(mode==='opening_range_break_5m'&&b.clock>=sessionStart+5){upper=oh;lower=ol}
    if(!mode.startsWith('ema')&&upper!=null&&Number.isFinite(pc)){
      if(pc<=upper&&b.close>upper&&b.close>b.open)side=1;
      if(pc>=lower&&b.close<lower&&b.close<b.open)side=-1;
    }
    const endClock=b.clock+tf,end=b.time+tf*60;
    const first=mode==='opening_range_break_5m'?sessionStart+10:sessionStart+5,max=mode.startsWith('ema')?sessionEnd-30:sessionStart+30;
    if(side&&endClock>=first&&endClock<=max&&(!universal||!ctx.optionSide||side===1)){
      const rawStop=side===1?b.low-(universal?tick:.05):b.high+(universal?tick:.05);
      const stop=universal?Number(((side===1?Math.floor:Math.ceil)(rawStop/tick+ (side===1?1e-8:-1e-8))*tick).toFixed(8)):rawStop;
      events.set(end,{side,stop});
    }
    // Plot confirmed values starting when known, never back-painted onto signal bars.
    b.fast=n>=33?e8:null;b.slow=n>=33?e33:null;b.upper=upper;b.lower=lower;
    last=b;
  }
  const known=new Map(groups.filter(b=>b.count===tf&&b.good&&(b.clock-sessionStart)%tf===0).map(b=>[b.time+tf*60,b]));
  let active=null,count=0,currentDay=null,blocked=false,prev=null,latest=null;const trades=[];
  for(let i=0;i<bars.length;i++){
    const b=bars[i],d=day(b.time),m=clock(b.time);let exited=false;
    if(d!==currentDay){active=null;count=0;blocked=false;latest=null;currentDay=d}
    if(active&&(!valid(b)||!prev||b.time!==prev.time+60)){values.event[i]=6;active.status='unknown';active=null;blocked=true;exited=true}
    if(!valid(b)){prev=b;continue}
    if(known.has(b.time))latest=known.get(b.time);
    if(latest){if(mode.startsWith('ema')){values.fast[i]=latest.fast;values.slow[i]=latest.slow}values.upper[i]=latest.upper;values.lower[i]=latest.lower}
    if(!active&&!blocked&&count<2&&!exited&&events.has(b.time)){
      const e=events.get(b.time),risk=e.side*(b.open-e.stop);
      if(risk>0&&(!universal||(e.stop>0&&b.open+e.side*reward*risk>0))){active={side:e.side,entry:b.open,stop:e.stop,target:b.open+e.side*reward*risk,entry_time:b.time};trades.push(active);count++;values.event[i]=e.side;values.direction[i]=e.side}
    }
    if(active){
      const a=active,s=a.side;values.entry[i]=a.entry;values.stop[i]=a.stop;values.target[i]=a.target;
      let price=null,code=0;
      if(b.time>=a.entry_time+3600||m>=exitClock){price=b.open;code=5}
      else if(s*(b.open-a.stop)<=0){price=b.open;code=3}
      else if(s*(b.open-a.target)>=0){price=a.target;code=2}
      else if(i<bars.length-1){const sl=s===1?b.low<=a.stop:b.high>=a.stop,tp=s===1?b.high>=a.target:b.low<=a.target;if(sl){price=a.stop;code=tp?4:3}else if(tp){price=a.target;code=2}}
      if(price!=null){values.exit[i]=price;values.event[i]=code+10;Object.assign(active,{exit:price,exit_time:b.time,status:'closed',reason:code});active=null}
    }
    prev=b;
  }
  return {values,trades,status:universal?`Chart research · ${symbol} · own price levels · 2R`:'Research · index levels only · 1m chart'};
}
export default function({registerIndicator}) {
  registerIndicator({
    id:'piyush-research',name:'Research Setups',category:'Custom',placement:'onchart',
    inputs:[{key:'mode',type:'select',label:'Setup (research reconstruction)',default:'previous_day_break_5m',options:Object.entries(MODES).map(([value,label])=>({value,label}))},{key:'reward',type:'select',label:'Structural target',default:3,options:[{value:3,label:'3R'},{value:4,label:'4R'}]}],
    plots:[['fast','EMA 8','#38bdf8'],['slow','EMA 33','#c084fc'],['upper','Resistance / range high','#f59e0b'],['lower','Support / range low','#f59e0b'],['entry','Index entry','#e2e8f0'],['stop','Structural stop','#ef4444'],['target','Index target','#22c55e']].map(([key,title,color])=>({key,title,type:'line',style:{color,lineWidth:2}})),
    calc(bars,settings,store,ctx){const r=compute(bars,settings,ctx);if(store)store.status=r.status;return r.values},
    markers({bars,values}){
      const out=[];for(let i=0;i<bars.length;i++){
        const side=values.direction[i],pad=Math.abs(bars[i].open)*.0002;
        if(side)out.push({time:bars[i].time,position:'atPrice',price:bars[i].open-side*pad,shape:side===1?'labelUp':'labelDown',size:'small',color:side===1?'#16a34a':'#dc2626',text:side===1?'CE bias':'PE bias'});
        const e=values.event[i];if(e>=12||e===6)out.push({time:bars[i].time,position:'atPrice',price:values.exit[i]??bars[i].open,shape:'circle',size:'small',color:e===12?'#22c55e':'#f59e0b',text:({6:'DATA GAP',12:'TARGET',13:'STOP',14:'SL FIRST · BOTH HIT',15:'TIME EXIT'})[e]});
      }return out;
    },
    table({bars,values,settings}){
      const i=bars.length-1;if(i<0)return null;const fmt=x=>x==null?'—':x.toFixed(2);
      if(!values.ready[i])return {rows:[[{text:'Research setups',bold:true}],[{text:'Switch to standard 1m NIFTY / SENSEX spot candles'}]]};
      return {rows:[[{text:'Research setups',bold:true},{text:MODES[settings.mode]||MODES.previous_day_break_5m}],[{text:'Chart required'},{text:'NIFTY / SENSEX spot · 1 minute'}],[{text:'Index entry / stop / target'},{text:[values.entry[i],values.stop[i],values.target[i]].map(fmt).join(' / ')}],[{text:'Rules'},{text:'2/day · 60 min · exit 15:15 IST'}],[{text:'Evidence'},{text:'Reconstructed; no stable option edge'}],[{text:'Levels'},{text:'Index points; not option premium'}]]};
    },
  });
}
