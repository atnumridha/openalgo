import json, math
from pathlib import Path
import pandas as pd
import pandas_ta as ta
cases=[]
for case in range(12):
 closes=[round(100+math.sin(i*(.08+case*.013))*((case%4)+1)+(.01*(case-6)*i),6) for i in range(140)]
 if case in (0,1,2,3):closes[-1]+=(-1 if case%2 else 1)*8
 bars=[dict(time=i*180,open=closes[max(0,i-1)],high=max(closes[max(0,i-1)],v)+.3,low=min(closes[max(0,i-1)],v)-.3,close=v) for i,v in enumerate(closes)]
 out={}
 for name,count in [('bollinger',100),('macd-bb',120),('supertrend',30)]:
  df=pd.DataFrame(bars[-count:])
  if name=='supertrend':
   st=ta.supertrend(df.high,df.low,df.close,length=20,multiplier=4.0)
   line=float(st.iloc[-1,0]);direction=int(st.iloc[-1,1]);dist=abs(closes[-1]-line)/closes[-1]
   side=('LONG' if direction==1 else 'SHORT') if dist<.01 else 'WAIT'
   out[name]={'side':side,'line':line,'distance':dist}
  else:
   bb=ta.bbands(df.close,length=100,lower_std=2.,upper_std=2.)
   bp=float(bb.iloc[-1,-1]); side='LONG' if bp<0 else 'SHORT' if bp>1 else 'WAIT'
   values={'percentB':bp}
   if name=='macd-bb':
    m=ta.macd(df.close,fast=21,slow=42,signal=9)
    macd=float(m.iloc[-1,0]);hist=float(m.iloc[-1,1]);values.update(macd=macd,hist=hist)
    side='LONG' if bp<0 and macd<0 and hist>0 else 'SHORT' if bp>1 and macd>0 and hist<0 else 'WAIT'
   out[name]={'side':side,**values}
 cases.append({'closes':closes,'expected':out})
Path('frontend/src/lib/trading/cryptoStrategyReference.json').write_text(json.dumps({'reference':'Hummingbot 9af100d; pandas-ta 0.4.71b0; TA-Lib 0.6.8','cases':cases},separators=(',',':'),allow_nan=False))
# Include actual long/short MACDBB signals, which are rarer than band excursions.
# These vectors exercise the full conjunction, not only WAIT outputs.
import numpy as np
rng=np.random.default_rng(4219)
found=set()
for attempt in range(100000):
 if len(found)==2: break
 changes=rng.normal(0,.4,140)
 changes[-45:]+=rng.choice([-1,1])*.10
 closes=np.cumsum(changes)+100
 if closes.min()<20: continue
 close=pd.Series(closes[-120:])
 band=ta.bbands(close,length=100,lower_std=2.,upper_std=2.)
 bp=float(band.iloc[-1,-1])
 if not (bp<0 or bp>1): continue
 mac=ta.macd(close,fast=21,slow=42,signal=9)
 m,h=float(mac.iloc[-1,0]),float(mac.iloc[-1,1])
 side='LONG' if bp<0 and m<0 and h>0 else 'SHORT' if bp>1 and m>0 and h<0 else 'WAIT'
 if side=='WAIT' or side in found: continue
 closes=[float(x) for x in closes]
 bars=[dict(time=i*180,open=closes[max(0,i-1)],high=max(closes[max(0,i-1)],v)+.3,low=min(closes[max(0,i-1)],v)-.3,close=v) for i,v in enumerate(closes)]
 df=pd.DataFrame(bars[-30:]);st=ta.supertrend(df.high,df.low,df.close,length=20,multiplier=4.)
 line=float(st.iloc[-1,0]);direction=int(st.iloc[-1,1]);dist=abs(closes[-1]-line)/closes[-1]
 st_side=('LONG' if direction==1 else 'SHORT') if dist<.01 else 'WAIT'
 cases.append({'closes':closes,'expected':{'bollinger':{'side':'LONG' if bp<0 else 'SHORT','percentB':bp},'macd-bb':{'side':side,'percentB':bp,'macd':m,'hist':h},'supertrend':{'side':st_side,'line':line,'distance':dist}}})
 found.add(side)
assert found=={'LONG','SHORT'},found
Path('frontend/src/lib/trading/cryptoStrategyReference.json').write_text(json.dumps({'reference':'Hummingbot 9af100d; pandas-ta 0.4.71b0; TA-Lib 0.6.8','cases':cases},separators=(',',':'),allow_nan=False))
print('Reference cases:',len(cases))
