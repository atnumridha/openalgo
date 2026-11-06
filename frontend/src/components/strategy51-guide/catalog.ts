import type { StrategyDefinition } from './types'
/** Paraphrased source rules. Local numerical choices are separately identified. */
export const STRATEGIES_51: readonly StrategyDefinition[] = [
  {
    id: '1.1',
    number: 1,
    title: 'Trading the Bollinger Bands',
    category: 'Swing',
    pages: [14, 29],
    entry:
      'long: Uptrend near upperBB -> gap down Y>X -> lowerBB support -> bullish candle high break. | short: Downtrend near lowerBB -> gap up X>Y -> upperBB rejection -> bearish candle low break.',
    stop: 'L:support candle low; S:resistance candle high.',
    target: 'L:upperBB; S:lowerBB.',
    exit: 'L:upperBB; S:lowerBB.',
    timeframe:
      'BB with basis hidden, bands 2 SD, EMA9(close); p17 unusually calls the strategy intraday with 30-minute entry/exit despite the swing chapter.',
    requirements: ['30m OHLC', 'session gaps', 'manual/local trend and support confirmation'],
    notes: [
      '**Discretionary chart candidate**: BB period unspecified, primary trend, support/rejection, gap scale/session and X/Y measurement timing unspecified. Distance test after a gap cannot be replaced by current trend alone.',
    ],
    local: [
      'BB20/2 explicitly local; session-open vs prior close gap and signal-bar X/Y measured at completed candle; local EMA20/50 trend context plus manual confirmation of gap/support sequence. Freeze chosen confirmation candle, supporting candle and BB target; do not claim these added definitions came from source.',
    ],
  },
  {
    id: '1.2',
    number: 2,
    title: 'Williams %R and MACD duo for Swing Trading',
    category: 'Swing',
    pages: [30, 35],
    entry:
      'long: %R overbought -> pullback/reverse at-50; aboveSMA14; green high break. | short: %R below-80 -> recover to-50; belowSMA14; red low break.',
    stop: 'L:swinglow; S:swinghigh.',
    target:
      'No executable target; >2R examples. Trade up to2days; second-half signal observation, exact hour missing.',
    exit: 'No executable target; >2R examples. Trade up to2days; second-half signal observation, exact hour missing.',
    timeframe:
      'actual strategy is Williams %R14 plus SMA14(close), 30-minute swing. **MACD is in the title but not in execution rules**; do not add MACD confirmation. Long price above SMA indicates uptrend; short below indicates downtrend.',
    requirements: [
      '30m OHLC',
      'Williams %R14',
      'SMA14',
      'confirmed swings',
      'explicit target convention',
    ],
    notes: [
      'MACD in title; actual execution uses Williams %R14 and SMA14, no MACD.',
      'No executable price target specified.',
      '**Chart candidate with target gap**: exact -50 touch tolerance/reversal definition, swing selection and target absent. No fixed book target can be synthesized.',
    ],
    local: [
      'state machine overbought→-50 retrace→rise (reverse for short), configured touch tolerance, completed bullish/bearish candle and confirmed swing SL. A frozen2R target would be **local**, with source target `not specified`.',
    ],
  },
  {
    id: '1.3',
    number: 3,
    title: 'Catching swings with MACD and Fibonacci retracement',
    category: 'Swing',
    pages: [36, 41],
    entry:
      'long: Uptrend fib pullback + MACD bullish cross + green atfib; above green CLOSE. | short: Unsupported:source long-only.',
    stop: 'Previous swinglow.',
    target: 'Above fib0/originalhigh or >=2R; ignore MACD sell signals for exit.',
    exit: 'Above fib0/originalhigh or >=2R; ignore MACD sell signals for exit.',
    timeframe:
      '30-minute; MACD chart12/26/9 EMA, Fibonacci retracements23.6/38.2/50/61.8/100%. **Long only** in source because its intended cash swing instrument cannot be shorted overnight.',
    requirements: ['30m OHLC', 'MACD12/26/9', 'selected Fibonacci impulse anchors'],
    notes: [
      'p38 MACD subtraction sign opposite standard chart 12/26/9 convention.',
      'Entry above green close, not high; early MACD cross may precede fib candle.',
      "**Discretionary chart candidate**; impulse/anchor selection and which fib level require rules. p38 describes subtracting12EMA from26EMA, opposite to screenshot's usual MACD; preserve as source conflict. Crossover can precede candle; source gives no allowed age.",
    ],
    local: [
      'canonical MACD sign from register declared as correction; user/confirmed swing anchors, record whether target branch is original-high or local2R. Require explicit age/tolerance settings; unsupported short stays unavailable.',
    ],
  },
  {
    id: '1.4',
    number: 4,
    title: 'Riding a breakout',
    category: 'Swing',
    pages: [42, 50],
    entry:
      'long: Daily high-volume rally -> body-connected triangle with contractingvolume -> solid bullish high-volume breakout; above CLOSE. | short: Unsupported:source cash long-only.',
    stop: 'Below lowertriangle trendline.',
    target: 'Minimum2R; avoid impulsive poor-RR candle.',
    exit: 'Minimum2R; avoid impulsive poor-RR candle.',
    timeframe:
      'daily chart, volume, body-connected trendlines. Long cash swing only. Uptrend; strong high-volume rally, then lower highs/higher lows converging into triangle with contracting volume.',
    requirements: ['daily OHLCV', 'manual/local body-connected triangle and volume thresholds'],
    notes: [
      '**Discretionary**: manual/body pivot trendlines; no numeric rally, triangle duration/touch count/convergence, volume thresholds, solid-body or impulsive-candle limits. Volume required.',
    ],
    local: [
      'manual validated triangle endpoints and confirmation; trendlines calculated from candle bodies, source low/high distinction retained. Quantified triangle detector would be labelled a local interpretation. Freeze lower-line SL at entry and2R minimum target; no wick-line substitution.',
    ],
  },
  {
    id: '1.5',
    number: 5,
    title: 'Swing trading with institutional moves',
    category: 'Swing',
    pages: [51, 63],
    entry:
      'long: First return old gapdemand; lowerlows -> zone -> fresh gapup closesgreen; buy high. | short: First return old gapsupply; higherhighs -> zone -> fresh gapdown closesred; sell low.',
    stop: 'L:below gap; S:p62 below gap conflicts p63 gapHIGH.',
    target: 'Major resistance/support or unspecifiedtrail. No second/third zone-touch entries.',
    exit: 'Major resistance/support or unspecifiedtrail. No second/third zone-touch entries.',
    timeframe:
      'monthly watchlist of highly liquid stocks, daily chart; previous gap-derived demand/supply zones. p58 says **first retracement only**; second/third touch explicitly avoided.',
    requirements: [
      'daily OHLCV',
      'liquid universe/turnover selection',
      'dated gap-zone bounds and touch count',
    ],
    notes: [
      'Short p62 SL below gap contradicts p63 high-of-gap example/diagram.',
      'General first retracement to old gap zone plus execution fresh reversal gap at old zone; retain both.',
      '**Discretionary + External universe/liquidity input**. Gap-zone bounds, liquid criteria, zone age and first-touch reset missing. Source short SL conflict is material.',
    ],
    local: [
      'accept manually annotated old zone, its creation gap and touch count; require fresh reversal gap/candle and reject touch>=2. If resolving short SL to gap high, cite example as resolution. Select one numerical resistance/support target; generic trail is insufficient to infer a fixed target.',
    ],
  },
  {
    id: '1.6',
    number: 6,
    title: 'Trading the breakouts with BB and width',
    category: 'Swing',
    pages: [64, 71],
    entry:
      'long: Squeeze/flatWidth -> upperBB break + risingWidth. | short: Squeeze/flatWidth -> lowerBB break + risingWidth.',
    stop: 'L:below middleBB; S:above middleBB.',
    target: 'L:closebelow middleBB; S:bullet says below, example above (conflict). No fixedtarget.',
    exit: 'L:closebelow middleBB; S:bullet says below, example above (conflict). No fixedtarget.',
    timeframe:
      'BB20-SMA basis,2SD and BB Width; swing preferred **above30 minutes**, although example uses30-minute chart. Sideways range→squeezed BB and flat width→break with rising width.',
    requirements: [
      'OHLC30m example or above30m stated preference',
      'BB20/2',
      'BB Width',
      'squeeze/flat thresholds',
    ],
    notes: [
      'Preferred above30m versus30m example.',
      'Short p71 exit-below-middle bullet contradicts exit-above-middle example.',
      'Break entry versus candle-high example.',
      '**Chart candidate with configuration/conflict gates**: squeeze/flat duration, width formula/threshold, entry variant,30 vs >30 timing unresolved.',
    ],
    local: [
      'explicitly choose source example-compatible30m or strict>30m, quantify squeeze/flat/rise and break on close; short exit above middle band as declared example-based correction. Initial numerical band SL frozen; current band is separate conditional exit. A fixed R target is local only.',
    ],
  },
  {
    id: '1.7',
    number: 7,
    title: 'ICHIMOKU Cloud Indicator',
    category: 'Swing',
    pages: [72, 78],
    entry:
      'long: Conversion>base (cross alerts) then closeabovecloud. | short: Conversion<base then closebelowcloud.',
    stop: 'SpanA; alternate pullbackSL optimization. Validate risk side.',
    target: '3R discussed; unspecifiedtrail. Short not separately targeted.',
    exit: '3R discussed; unspecifiedtrail. Short not separately targeted.',
    timeframe:
      'conversion9/base26/spanB52,26 displacement;1-hour or daily swing. Source says conversion above base for longs/below for shorts; close above/below cloud required.',
    requirements: ['1h or daily OHLC', 'Ichimoku9/26/52 displacement26'],
    notes: [
      'SpanB prose omits division by2.',
      'Pullback SL optimization versus spanA SL examples.',
      '**Chart candidate**: spanB divide-by2 missing in prose; pullback SL variant vs spanA; cross freshness unspecified. Current plotted cloud must be aligned correctly. SpanA must be on valid SL side; cannot force a negative-risk plan.',
    ],
    local: [
      'canonical high/low midpoint formulas with declared correction, completed-bar cross then cloud confirmation; choose spanA vs manual pullback variant explicitly. Display3R as selected interpretation (source describes, not hard mandates); no future-cloud comparison.',
    ],
  },
  {
    id: '2.1',
    number: 8,
    title: 'Moving average and Fibonacci',
    category: 'Intraday',
    pages: [82, 89],
    entry:
      'long: Above rising200MA; fibsupport green; buy high. | short: Below falling200MA; fibresistance red; bullet sellHIGH vs exampleLOW.',
    stop: 'L:lower fib level; S:upper fib level.',
    target: 'Fib0/impulse destination or >=2R.',
    exit: 'Fib0/impulse destination or >=2R.',
    timeframe:
      '5-minute, source calls it **200-day Moving Average on a5-minute chart**, MA type unspecified. Upward inclination matters for long, downward for short; close on appropriate side alone insufficient. Fibonacci impulse anchors low→high long/high→low short.',
    requirements: ['5m OHLC', 'explicit200-bar or daily200 MA interpretation/type', 'fib anchors'],
    notes: [
      '200-day MA on5m ambiguous vs200 chart-bars; MA type missing.',
      'Short bullet sell high versus example low.',
      '**Discretionary chart candidate / potentially Multi-TF**: 200 daily-period vs200 chart-bar ambiguity, SMA/EMA missing, MA slope interval, fib selection/support tolerance missing, short entry conflict. Source no exact intraday cutoff/trail/re-entry.',
    ],
    local: [
      'explicitly select and disclose200-bar SMA on5m as a local interpretation, not a sourced200-day calculation; alternatively supply daily200 MA as distinct configured variant. Require signed slope and anchors; resolve short entry using example low only with disclosure. No silent EMA200 substitution.',
    ],
  },
  {
    id: '2.2',
    number: 9,
    title: 'Ride the trend with Supertrend',
    category: 'Intraday',
    pages: [90, 97],
    entry:
      'long: BreakR1 + aboveST + green; aboveclose. | short: BreakS1 + belowST + red; belowclose (examplelow).',
    stop: 'ST; short example swinghighnearST.',
    target: 'L:closebelowST; S:closeaboveST or discretion. Example intraday cutoff15:15.',
    exit: 'L:closebelowST; S:closeaboveST or discretion. Example intraday cutoff15:15.',
    timeframe:
      '5-minute, Supertrend ATR **7**, Standard Pivot Points with only R1/S1, source defaults for pivots; central P disabled. Range R1–S1 considered sideways.',
    requirements: ['5m OHLC', 'completed pivot-anchor HLC', 'ST ATR7 plus configured multiplier'],
    notes: [
      'Short below candle close in checklist versus low in example.',
      'ATR7 specified but ST multiplier absent.',
      '**Chart candidate with configuration gates**: ST multiplier absent; pivot type/anchor not explicit in prose (chapter2.7 screenshot Traditional/Auto is not automatically a rule here); close vs low variant for short.',
    ],
    local: [
      'ATR7 with explicitly configured multiplier, previous completed session Traditional pivots as disclosed convention; freeze initial ST SL and optionally use ST conditional exit. Apply15:15 exchange local-time exit for this variant, not all book strategies. No trade inside R1/S1; fail if daily HLC unavailable.',
    ],
  },
  {
    id: '2.3',
    number: 10,
    title: 'Analyzing Pivot Points Using VWAP and Standard Deviations',
    category: 'Intraday',
    pages: [98, 107],
    entry:
      'long: Red CLOSEbelow lower2SD -> green reversal -> later highbreak. | short: Green CLOSEabove upper2SD -> red reversal -> later lowbreak.',
    stop: 'L:greenlow; S:redhigh checklist vs greenhigh caption.',
    target:
      'T1VWAP,T2opposite2SDband; preferred2R. Avoid another same-security setup after trade (reset unspecified).',
    exit: 'T1VWAP,T2opposite2SDband; preferred2R. Avoid another same-security setup after trade (reset unspecified).',
    timeframe:
      '5-minute VWAP, only band#2 upper/lower (2SD) enabled. This is VWAP mean reversion; **not standard pivot-point levels despite title**.',
    requirements: [
      '5m OHLCV with valid traded volume',
      'exchange-session calendar',
      'VWAP2SD bands',
    ],
    notes: [
      'Short p106 caption green-candle-high SL versus p107 red-candle-high checklist.',
      '**Chart candidate** when valid traded volume/session data exist; VWAP band variance equation and SL caption conflict absent resolution.',
    ],
    local: [
      'register VWAP formula, strict completed outside close→opposite-color candle→subsequent high/low break. Do not trigger at first touch or reuse pre-confirmation high/low. Select one target branch for frozen plan, retain both in guide. Once-per-symbol-per-session is a local cooldown interpretation. Use red reversal SL as explicit checklist-based choice.',
    ],
  },
  {
    id: '2.4',
    number: 11,
    title: 'Buy/sell with RSI and Volume Oscillator',
    category: 'Intraday',
    pages: [108, 115],
    entry:
      'long: Uptrend dip RSI30 + VO~-30 in tandem; example bullishresistancebreak. | short: Downtrend pullback RSI70 + VO~+30; example support-candlelowbreak.',
    stop: 'L:swinglow; S:swinghigh.',
    target: 'L:RSI reaches70; S:RSI reaches30. Conservative2R described; no fixedprice.',
    exit: 'L:RSI reaches70; S:RSI reaches30. Conservative2R described; no fixedprice.',
    timeframe:
      '5-minute RSI and Volume Oscillator, conventional RSI30/70. Both move in tandem near extreme VO-30%/+30%; actual VO fast/slow lengths, MA type and exact RSI period not specified in prose.',
    requirements: ['5m OHLCV', 'RSI period choice', 'VO fast/slow/type/threshold configuration'],
    notes: [
      'p114 short caption oversold versus short overbought execution.',
      'VO periods/type and near thresholds missing.',
      '**Discretionary chart candidate**: missing VO configuration, near tolerance, exact reversal/synchronization and universal candle entry; trend definition absent. Do not fabricate two MA periods. No exact trail/re-entry/cutoff.',
    ],
    local: [
      'keep unavailable until VO periods/type and tolerance chosen explicitly; RSI14 only as local default. Use manual confirmation of price trigger or disclose a strict bullish-high/bearish-low local trigger. Indicator-based profit exit is not a known price target; a local2R target must be labelled local.',
    ],
  },
  {
    id: '2.5',
    number: 12,
    title: 'Wait and trade the Pullback',
    category: 'Intraday',
    pages: [116, 125],
    entry:
      'long: Pivot pullback withoutbreak reversal or afterbreak continuation; bullishcandle. | short: Pivot pullback withoutbreak reversal or afterbreak continuation; bearishcandle.',
    stop: 'L:candlelow; S:candlehigh.',
    target: 'Next pivot; skip to following if next too near (threshold absent).',
    exit: 'Next pivot; skip to following if next too near (threshold absent).',
    timeframe:
      '5-minute Standard Pivot Points at default settings. Supports **both reversal and continuation**. Pullback#1 occurs without breaking pivot (reversal); pullback#2 occurs after breaking it (continuation). Do not require continuation-only trend bias and erase source reversal branch.',
    requirements: [
      '5m OHLC',
      'completed pivot-anchor HLC',
      'manual/local pivot pullback classification',
    ],
    notes: [
      '**Discretionary chart candidate**: pivot anchor/default type, hover, pullback shape and skip-near threshold missing.',
    ],
    local: [
      'explicitly identify pivot and variant; manual pullback confirmation or local breakout→retest/rejection state machine. Adopt completed candle high/low break only as a local trigger. Declare pivot calculation/anchor and minimum R distance used to decide skip; freeze chosen pivot target.',
    ],
  },
  {
    id: '2.6',
    number: 13,
    title: 'Double RSI',
    category: 'Intraday',
    pages: [126, 133],
    entry:
      'long: HourlyRSI>50 +5mRSI<30 +green; highbreak. | short: HourlyRSI<50 +5mRSI>70 +red; lowbreak.',
    stop: 'L:greenlow; S:redhigh.',
    target: 'L:5mRSI first>70 then crossDOWN70; S:first<30 then crossUP30. No fixedprice.',
    exit: 'L:5mRSI first>70 then crossDOWN70; S:first<30 then crossUP30. No fixedprice.',
    timeframe:
      '5-minute chart with default RSI14 (screenshot `RSI5 14close...`) and second **hourly RSI14** (`RSI60 14close...`). Not two different RSI lengths. Primary bias hourlyRSI>50 long/<50 short.',
    requirements: ['5m OHLC', 'independent completed1h OHLC as-of5m signal', 'RSI14 on both'],
    notes: [
      '**Multi-TF chart candidate**. Need sufficient1h history, not5mRSI resampled/interpolated; source does not choose live-vs-completed hourly values.',
    ],
    local: [
      'use last completed hourlyRSI as-of each5m close, strict crossings and a separate oversold/overbought state. Signal candle and later price break ordered. A single frozen price target is local; otherwise display conditional exit rule and target unavailable.',
    ],
  },
  {
    id: '2.7',
    number: 14,
    title: 'CPR with trend following',
    category: 'Intraday',
    pages: [134, 147],
    entry:
      'long: Wide:supportreversal; narrow:break any support/CPR/resistance frombelow. | short: Wide:resistancereversal; narrow:support/CPR break.',
    stop: 'L:buyingcandlelow (narrow example swinglow); S:reversal/breakdowncandlehigh.',
    target: 'Nextpivot or unspecifiedtrail; ideal2R for longbranches.',
    exit: 'Nextpivot or unspecifiedtrail; ideal2R for longbranches.',
    timeframe:
      '5-minute CPR and pivot supports/resistances. Narrow CPR indicates trending regime; wide indicates range. CPR width has **no numerical cutoff**. p135 R1 formula is visibly `(P×2)-2`, not a text-extraction artefact; p135 chart header shows `Pivots Traditional Auto` but source prose does not define anchor policy.',
    requirements: [
      '5m OHLC',
      'completed pivot-anchor HLC',
      'explicit CPR formula and width classification',
    ],
    notes: [
      'p135 R1 visibly printed2P-2; no CPR equation/width threshold.',
      'Long candle-low SL versus example swing-low variant.',
      '**Discretionary chart candidate**: exact CPR formula/width, source R1 error, trigger candle/close-vs-high and SL alternatives; unspecified trailing rule. Range branch must not be filtered out by continuation-only trend filter.',
    ],
    local: [
      'register previous-session pivots and CPR formula/correctedR1 disclosed; width normalized by price or ATR with explicit thresholds (not author thresholds). Manual wide/narrow selection until configured. For fixed plan choose next pivot and one SL branch; retain four branches in guide.',
    ],
  },
  {
    id: '3.1',
    number: 15,
    title: 'Basics of Dow theory',
    category: 'Trend',
    pages: [150, 157],
    entry:
      'long: Uptrend previoushighbreak; buy breakingcandlehigh; mandatory unspecifiedmomentumoscillator. | short: Downtrend previouslowbreak; sell breakingcandlelow; mandatory unspecifiedmomentumoscillator.',
    stop: 'L:swinglow; S:swinghigh.',
    target: 'Next swinghigh/low or unspecifiedtrail. Future swing target not known atsignal.',
    exit: 'Next swinghigh/low or unspecifiedtrail. Future swing target not known atsignal.',
    timeframe:
      'any security, timeframe chosen by trading style. Higher highs/higher lows define uptrend; lower highs/lower lows downtrend; accumulation/markup/distribution/markdown context.',
    requirements: [
      'chosen-timeframe OHLC',
      'confirmed swing structure',
      'explicit momentum oscillator confirmation',
    ],
    notes: [
      '**Discretionary chart candidate** until oscillator convention and swing hierarchy selected. Next future swing high/low cannot be used as a known entry-time target; trailing formula absent. No exact session/re-entry rule.5m/1m fib mention in example is illustrative, not mandatory multi-TF rule.',
    ],
    local: [
      'confirmed local3L/3R pivots for structure and explicitly selected oscillator (e.g. RSI14>50/<50 labelled local). Source break candle must finish before any candle-high confirmation that depends on its final high. Known pre-existing next structure target or local2R; never future hindsight pivot.',
    ],
  },
  {
    id: '3.2',
    number: 16,
    title: 'Smart Money Concept',
    category: 'Trend',
    pages: [158, 173],
    entry:
      'long: Aggressivefall -> strongupshift -> lowerwickOB/fairvaluezone -> retrace/reversegreen -> highbreak. | short: Aggressiverally -> strongdownshift -> upperwickOB/fairvaluezone -> retrace/reversered -> lowbreak.',
    stop: 'L:greenlow or swinglow; S:redhigh or swinghigh.',
    target:
      'Nextresistance/support. May reverse before exactzone; perfectOB/FV not always present.',
    exit: 'Nextresistance/support. May reverse before exactzone; perfectOB/FV not always present.',
    timeframe:
      'chosen security; no universal timeframe (1-minute example). Aggressive moves, shift in direction, order-block zones, fair-value-candle zone; BoS new high and CHoCH trend shift are described, **not prescribed as mandatory coded BoS→CHoCH entry sequence**.',
    requirements: [
      'chosen-timeframe OHLC',
      'manual/disclosed order-block/fair-value zone',
      'manual/local reversal',
    ],
    notes: [
      '**Discretionary**: aggressive/explosive, zone endpoints, swing shift, near-zone tolerance, primary/HTF zones and target selection lack numeric rules. Charts infer institutional activity, cannot prove orders/participants. No explicit trail/re-entry/cutoff.',
    ],
    local: [
      'manual zone + creation/confirmation candle records; optional explicitly labelled local imbalance detector. One selected candle-SL or swing-SL and pre-existing resistance/support. No automatic plan while zone/target missing.',
    ],
  },
  {
    id: '3.3',
    number: 17,
    title: 'Mastering Elliott Wave Theory for Profitable Trading',
    category: 'Trend',
    pages: [174, 183],
    entry:
      'long: Manual waves:at2 or4 correction, bullishcandlehigh. | short: Prose swinghigh B and C with bearishcandlelow; conflicts/ambiguity with downward-wave diagram.',
    stop: 'L:swinglow; S:swinghigh.',
    target: 'Next swinghigh/low; ideal2R. Wave3 longest;4low>=1high;5shorter3longer1;2low<4low.',
    exit: 'Next swinghigh/low; ideal2R. Wave3 longest;4low>=1high;5shorter3longer1;2low<4low.',
    timeframe:
      'manually mark swings/waves; no mandatory timeframe (p182 diagram is4h). Five motive waves then A/B/C correction.',
    requirements: [
      'chosen-timeframe OHLC',
      'manual as-of Elliott wave labels and chosen opportunity',
    ],
    notes: [
      'Short checklist B and C swing highs ambiguous against p182 downward0-5/upwardabc diagram.',
      'Later-wave validation cannot be used to backdate earlier-wave entries.',
      '**Discretionary/manual only**; waves are subjectively counted and later waves required to validate some earlier rules create hindsight risk. No trailing/re-entry/session rule.',
    ],
    local: [
      'require human-supplied as-of wave labels/anchors and selected long opportunity; short remains incomplete until explicit label interpretation. Do not auto-generate exact-source Elliott from3L/3R pivots or use future wave3/5 information to qualify historical wave2.',
    ],
  },
  {
    id: '3.4',
    number: 18,
    title: 'Mastering Fractal-Based Trading: A Personal Approach',
    category: 'Trend',
    pages: [184, 195],
    entry:
      'long: AboveSMA50; confirmed4L4R priorfractalhigh broken bygreen. | short: BelowSMA50; confirmed4L4R priorfractallow broken.',
    stop: 'Oppositefractal or nearswing ifdistant; checklist swinglow/belowSMA long, swinghigh/aboveSMA short.',
    target:
      'Rejection/resistance long; support/reversal short; ideal2R/discussion2or3R. No explicittrailalgorithm.',
    exit: 'Rejection/resistance long; support/reversal short; ideal2R/discussion2or3R. No explicittrailalgorithm.',
    timeframe:
      'Williams Fractal Trailing Stops by SimpleCrypto, **4 back/4 forward**; SMA50 (called50-day in checklist, screenshot Chart timeframe/1h chart; explanation50-period). Any timeframe/market per conclusion; SMA period adjustable in discussion, illustrated50.',
    requirements: [
      'chosen-timeframe OHLC',
      'confirmed4L/4R fractals',
      'SMA50',
      'explicit SL/exit branch',
    ],
    notes: [
      '50-day wording versus50-period/Chart-timeframe example.',
      'Named custom script exact parity unverified;4L/4R required.',
      '**Chart candidate**, with discretionary optimal proximity/exhaustion/exit branch. Custom script implementation not available; exact parity unproven. Fractal needs4 following candles before eligibility;3L/3R substitution is wrong. Tie handling unspecified.',
    ],
    local: [
      'strict4L/4R pivot engine as register, SMA50 of selected timeframe disclosed. Use confirmed opposite swing SL and explicitly local2R fixed target where no known rejection target; label approximation to named script. No future fractal leakage.',
    ],
  },
  {
    id: '3.5',
    number: 19,
    title: 'Trading with Renko Charts',
    category: 'Trend',
    pages: [196, 203],
    entry:
      'long: Renko support +greenbrick +RenkoRSI/StochRSIoversold; map tocandleentry. | short: Renko resistance +redbrick +RenkoRSI/StochRSIoverbought; map tocandleentry.',
    stop: 'Realcandlestick swinglow/high.',
    target: 'Minimum3R or unspecifiedtrail. CandlestickRSI neednot beextreme.',
    exit: 'Minimum3R or unspecifiedtrail. CandlestickRSI neednot beextreme.',
    timeframe:
      'can use any, recommended15-minute. Renko sourceClose/ATR box assignment/ATR14; RSI14 and StochRSI screenshot3,3,14,14 on **Renko**. Long-term S/R manually marked on Renko; candlestick chart used for actual entry/SL/management.',
    requirements: [
      '15m suggested OHLC',
      'completed Close/ATR14 Renko representation and candle-time mapping',
      'RenkoRSI14 and StochRSI3/3/14/14',
      'manual RenkoS/R',
    ],
    notes: [
      '**Transformed-chart + Discretionary** (two chart representations; not necessarily two timeframes). No brick reversal/ATR sizing/recalculation algorithm, oscillator exact thresholds or K/D gate, support-age or exact candle-price trigger.',
    ],
    local: [
      'manual completed Renko signal and S/R, reproducible brick history/as-of map and completed15m candle anchor. No synthetic Renko brick price as executable entry or hindsight-rebuilt brick backtest. Fixed3R plan only once actual candle entry/SL supplied.',
    ],
  },
  {
    id: '3.6',
    number: 20,
    title: 'Donchian Channel and Pullback',
    category: 'Trend',
    pages: [204, 211],
    entry:
      'long: Upperbandtouch -> pullback -> upperbandrebreak. | short: Lowerbandtouch -> pullback -> lowerbandrebreak.',
    stop: 'L:belowmid; trailfirstbreakoutlow after2bullish; S:abovemid, trailfirstbreakdownhigh after2bullish bullet vs2bearish example.',
    target: 'Typical2R. Observe3-4candlepullback narrative; waitforpullback, notfirstbreak.',
    exit: 'Typical2R. Observe3-4candlepullback narrative; waitforpullback, notfirstbreak.',
    timeframe:
      'preferred timeframe, Donchian defaultN unspecified. Bands HHN/LLN/midpoint. Narrative observes3–4 candle pullback before sharp move; execution requires a pullback, not simply first breakout.',
    requirements: [
      'chosen-timeframe OHLC',
      'configured DonchianN',
      'prior-channel boundaries',
      'touch-pullback-rebreak sequence',
    ],
    notes: [
      'Short trail bullet two bullish versus example two bearish candles.',
      'Default channel N absent; current-bar inclusive strict breakout impossible.',
      '**Chart candidate with parameter/conflict gates**: N, touch tolerance, minimum pullback/depth and whether3–4 mandatory, breakout intrabar/close missing. Current-bar channel includes current high/low, so literal strict `high>currentUpper` impossible.',
    ],
    local: [
      'configureN and use prior completed channel for break, ordered touch→at-least-one explicit retracement→rebreak; choose stricter3–4-bar variant if desired as local. Short trail on two bearish candles only as declared example-based resolution; move SL one direction only. Frozen initial2R is source-described typical target.',
    ],
  },
  {
    id: '3.7',
    number: 21,
    title: 'Gann Fan',
    category: 'Trend',
    pages: [212, 218],
    entry:
      'long: Uptrend selectedfan support; optional lowerBBconfluence. | short: Downtrend selectedfan resistance; optional upperBBconfluence/redweakness.',
    stop: 'Shortexample1x2 entry/1x3 SL; genericlongrung absent.',
    target: '3R shortexample; fanrungs target/SL/turns; exactgeneric exits absent.',
    exit: '3R shortexample; fanrungs target/SL/turns; exactgeneric exits absent.',
    timeframe:
      'any intraday; Gann fan and Linear Regression over selected price leg, optional default BB. p214 screenshot `LinReg 100 close 2 2` while text describes 20-period endpoint line and instructs anchoring regression bottom→top/uptrend or top→bottom/downtrend.',
    requirements: [
      'intraday OHLC',
      'manual fan anchors and price-time scale',
      'regression interpretation',
      'selected fan entry/SL/target',
    ],
    notes: [
      'LinReg100 screenshot versus20-period explanation; fan scale/anchors not specified.',
      '**Discretionary/manual only**: fan anchor, chart price-time scaling, regression 100 vs 20, regression channel vs line, which rung/mean mapping, tolerance and target selection unclear. Screenshot units/scale matter; a fan is not a freely interchangeable ATR slope.',
    ],
    local: [
      'accept user-selected fan anchors, scale, trend and exact entry/SL/target levels; optionally calculate selected fixed fan lines only under disclosed price-per-bar convention. Source default BB needs declared settings. Do not advertise automatic Gann from an uncalibrated OHLC chart or force long to 1x2/1x3 by symmetry.',
    ],
  },
  {
    id: '4.1',
    number: 22,
    title: 'Moving with Macro trends',
    category: 'Positional',
    pages: [222, 229],
    entry:
      'long: Dailyuptrend -> P/S1/S2support -> bullishhighbreak. | short: Dailydowntrend -> P/R1/R2resistance -> bearishlowbreak.',
    stop: 'L:below supportarea; S:above resistancearea.',
    target: 'Nextpivot or trailto2R. Cashlong/derivativesshort.',
    exit: 'Nextpivot or trailto2R. Cashlong/derivativesshort.',
    timeframe:
      'daily, Standard Pivot Points P,S1,S2,R1,R2. Positional weeks–months, long cash allowed; shorts intended for derivatives. This is **price/pivot trend trading**, not a required macroeconomic feed despite title.',
    requirements: [
      'daily OHLC',
      'configured completed pivot-anchor HLC',
      'trend and support/resistance confirmation',
    ],
    notes: [
      '**Chart candidate with discretionary support/trend gates**. Pivot calculation type and anchor period not explicitly fixed: daily chart does not imply daily pivot anchor. No exact support-area buffer, trail algorithm or re-entry. Book does not supply macro data requirement.',
    ],
    local: [
      'require configured completed higher anchor (weekly/monthly if selected) instead of assuming daily-session pivots; manual or local confirmed swings for trend and support-zone validation. Freeze one next known pivot target and source support SL. Show derivative-only short instrument prerequisite; no actual orders.',
    ],
  },
  {
    id: '4.2',
    number: 23,
    title: 'Supertrend with RSI',
    category: 'Positional',
    pages: [230, 237],
    entry: 'long: AboveST +RSIcrossUP60; example greenhigh. | short: BelowST +RSIcrossDOWN40.',
    stop: 'L:swinglow checklist vs STexample; S:swinghigh; thereafterSTtrail.',
    target: 'L:closebelowST; S:closeaboveST. No fixedprice. Derivativesshort.',
    exit: 'L:closebelowST; S:closeaboveST. No fixedprice. Derivativesshort.',
    timeframe:
      'positional weeks/month, examples appear daily context, but no explicit timeframe instruction in checklist. RSI over 60 bullish, below 40 bearish, 40–60 sideways; ST direction. Neither RSI period nor ST length/multiplier fixed in prose.',
    requirements: ['positional timeframe choice', 'OHLC', 'RSI period choice', 'ST parameters'],
    notes: [
      'Initial long SL swing low checklist versus ST example.',
      'Timeframe and ST/RSI parameters not explicit.',
      '**Chart candidate with configuration gates**: timeframe, RSI14 default interpretation, ST params, entry exact level and initial SL variant missing. Source does not give fixed target; R examples not future performance. No re-entry/cutoff.',
    ],
    local: [
      'daily RSI14 and explicitly configured ST as disclosed choices; choose checklist swing SL vs example ST SL and freeze. Maintain 40/60 cross state, not merely current state after an old cross. Conditional ST exit can accompany local fixed R target but must be labelled separately.',
    ],
  },
  {
    id: '4.3',
    number: 24,
    title: 'Sectoral Analysis: A powerful way to trade the markets',
    category: 'Positional',
    pages: [238, 245],
    entry:
      'long: SectorRS crosses aboveNifty50 -> choose highest-weight sectorconstituent -> buy. | short: Unsupported:source longresearch only.',
    stop: 'Absent.',
    target: 'Absent. Need datedweights, benchmarkmethod and localrisk plan.',
    exit: 'Absent. Need datedweights, benchmarkmethod and localrisk plan.',
    timeframe:
      'positional; sector index price compared with Nifty 50 via named Relative Strength or chart compare. No mandatory timeframe/RS formula/lookback/normalization. Fundamental/macro approaches are explained as alternatives; actual execution uses technical comparison.',
    requirements: [
      'sector-index and Nifty50 aligned history',
      'dated sector constituent weights/membership',
      'explicit RS/comparison method',
      'manual/local risk plan',
    ],
    notes: [
      'RS indicator formula versus normalized compare method ambiguous.',
      'No SL/target/exit supplied; historical weights not current.',
      '**External + multi-symbol + Discretionary**, not chart-only. Requires sector/benchmark synchronized history and dated constituent weights/membership; price-normalization vs actual RS indicator is ambiguous. Cannot produce a source-derived risk plan because SL and exit absent.',
    ],
    local: [
      'show research/manual checklist until benchmark method, as-of weights, entry and local SL/target selected. Do not use a single stock RSI as sector Relative Strength, invent a stop, or claim current weights from 2023 screenshot. No automatic frozen plan from source alone.',
    ],
  },
  {
    id: '4.4',
    number: 25,
    title: 'M & W Positional trading strategy using RSI',
    category: 'Positional',
    pages: [246, 251],
    entry:
      'long: RSI14 below30 formsW then returnsabove30. | short: RSI14 above70 formsM then returnsbelow70.',
    stop: 'Nearestprice swingnearentry.',
    target: 'L:RSI70; S:RSI30. Optional unspecifiedtrail. Patterns onRSI, notprice.',
    exit: 'L:RSI70; S:RSI30. Optional unspecifiedtrail. Patterns onRSI, notprice.',
    timeframe:
      'daily, RSI14(close), M/W shapes **on oscillator, not necessarily price**. Primary zones 70/30; 60/40 optional alternate mentioned with warning accuracy changes.',
    requirements: [
      'daily OHLC',
      'RSI14',
      'manual/local oscillatorW/M detection',
      'confirmed price swing',
    ],
    notes: [
      '**Discretionary chart candidate**: numeric oscillator pivot/twin-peak tolerance, intervening neckline depth, number of bars and pattern confirmation absent. Price M/W cannot substitute; simply crossing30/70 without two troughs/peaks is insufficient.',
    ],
    local: [
      "manual RSI W/M anchors or explicit local oscillator-pivot detector, require completed pattern and actual threshold return crossing. Price swing anchors must be available as-of signal. Indicator exit isn't a fixed price target; any frozen R target is local. Do not use future second trough confirmation to backdate signal.",
    ],
  },
  {
    id: '5.1',
    number: 26,
    title: '3-minute scalp trading strategy using Parabolic SAR, RSI, and Hieken Ashi',
    category: 'Scalping',
    pages: [254, 261],
    entry:
      'long: 3m bullishHA +SARbelow +RSI>50; highbreak; cross/retestvariant. | short: 3m bearishHA +SARabove +RSI<50; lowbreak.',
    stop: 'Parabolic SAR reference.',
    target: '2R; halfat1R ifmultipleqty. Longexample SARtouch exit.',
    exit: '2R; halfat1R ifmultipleqty. Longexample SARtouch exit.',
    timeframe:
      '3-minute HA candles, RSI14(close), SAR start.02/step.02/max.2 (screenshot). HA bullish defined as no lower body/bearish no upper body (likely wick terminology; disclose interpretation).',
    requirements: [
      '3m real OHLC',
      'HA representation',
      'RSI14',
      'SAR.02/.02/.2',
      'explicit indicator input/mapping convention',
    ],
    notes: [
      'HA no-lower/upper-body language interpreted as wick requires disclosure.',
      'RSI50 cross versus50-pullback example; raw versus HA indicator sources not specified.',
      '2R checklist with SAR-touch management example.',
      '**Transformed-chart chart candidate**: whether RSI/SAR run on synthetic HA or raw prices not explicit; HA wick/body wording, crossover vs persistent state/pullback variant, synthetic vs real entry high/low needs disclosure.',
    ],
    local: [
      'keep HA for confirmation, real candle high/low for risk/executable levels and RSI/SAR on explicit selected source. State this mapping is local. Choose strict cross or 50-retest variant; do not falsely report 2R fixed target and changing SAR SL as identical frozen risk. Preserve partial rule in guide even for single target branch.',
    ],
  },
  {
    id: '5.2',
    number: 27,
    title: 'RSI Divergence + Bollinger Bands Scalping Strategy',
    category: 'Scalping',
    pages: [262, 271],
    entry:
      'long: 1m lowerBB/lowerlows withRSI nonmatching -> green; example highbreak. | short: UpperBB/higherhighs withRSI nonmatching -> red; example lowbreak.',
    stop: 'L:greenlow; S:redhigh.',
    target: 'L:upperBB; S:lowerBB. No required RSI30/70extreme.',
    exit: 'L:upperBB; S:lowerBB. No required RSI30/70extreme.',
    timeframe:
      '1-minute BB (middle SMA20) and RSI; no explicit RSI period/BB SD in execution prose. Bullish divergence price lower lows but RSI not lower; bearish price higher highs but RSI not higher. This is momentum divergence, not mandatory oversold 30/overbought 70 RSI.',
    requirements: [
      '1m OHLC',
      'RSI period choice',
      'BB20 with specified SD',
      'paired divergence pivots',
    ],
    notes: [
      'Long near-lower-band checklist versus below-band narrative; green formation versus high-break example.',
      '**Discretionary chart candidate**: divergence swing pairing/tolerance/lookback, equal RSI treatment, band near vs outside and exact trigger absent. No trailing/re-entry/session cutoff. Examples 2R/3R are not required fixed targets.',
    ],
    local: [
      'explicitly BB20/2 and RSI14 as local defaults; completed confirmed price pivots with aligned RSI observations, no future pivot backdating. Require manual divergence until numerical detector selected; use completed reversal high/low break as local example-compatible trigger. Freeze opposite band price at setup, show later band movement separately.',
    ],
  },
  {
    id: '5.3',
    number: 28,
    title: 'Scalp trading with RSI and VWAP',
    category: 'Scalping',
    pages: [272, 279],
    entry:
      'long: 1m RSIoversold<30 +CENTRALVWAP support. | short: RSIoverbought>70 +CENTRALVWAP rejection.',
    stop: 'L:belowVWAP; S:aboveVWAP.',
    target:
      'OppositeVWAPband (indexmissing), or unspecifiedtrail. Not outside-band reversalstrategy2.3.',
    exit: 'OppositeVWAPband (indexmissing), or unspecifiedtrail. Not outside-band reversalstrategy2.3.',
    timeframe:
      '1-minute, default RSI (screenshot 14) and session VWAP with `hlc3`, band settings shown 1,2,3; no specific target-band index in prose.',
    requirements: [
      '1m OHLCV',
      'valid traded volume and session calendar',
      'RSI14',
      'sessionhlc3VWAP',
      'chosen targetband',
    ],
    notes: [
      '**Discretionary chart candidate**, session reset and real volume needed. No exact support/rejection geometry or candle trigger, band multiplier choice, SL buffer or trail recurrence. No re-entry/cutoff. This is central VWAP support/rejection; do not replace with lower/upper-band touch like 2.3.',
    ],
    local: [
      'source session hlc3 VWAP plus local variance equation; configured target k=1/2/3 and SL buffer explicit. Manualcentral VWAP retest confirmation or labelled local tolerance/candle trigger; no volume→no valid plan. Fixed target is chosen band snapshot, not changing future band.',
    ],
  },
  {
    id: '5.4',
    number: 29,
    title: 'Scalping 1 Minute Consolidation Breakouts',
    category: 'Scalping',
    pages: [280, 286],
    entry:
      'long: 1m pre-existinguptrend ->4-5smallbodywickrange -> highbreak. | short: Pre-existingdowntrend ->4-5barconsolidation -> lowbreak.',
    stop: 'L:breakoutcandlelow; S:breakdowncandlehigh.',
    target: '>=3R; mandatory10minutes fromentry exitifneitherSLnorTP hit.',
    exit: '>=3R; mandatory10minutes fromentry exitifneitherSLnorTP hit.',
    timeframe:
      '1-minute, experienced traders; highly liquid stock/index recommended. Pre-established trend only, then next **4–5 candles** make small-body wick range.',
    requirements: [
      '1m OHLC',
      'liquid-universe selection',
      'pre-established trend',
      '4-5-bar consolidation',
      '10-minute timer',
    ],
    notes: [
      '**Chart candidate with pattern gates**: trend definition, small-body/wick thresholds and range overlap/height not numeric; liquidity criterion external/manual if selecting universe. Source does not insist candle-close breakout vs intrabar break.',
    ],
    local: [
      "local confirmed structure/EMA20/50 trend and configured 4- or 5-bar range rules; use completed break candle and subsequent entry when requiring that candle's final SL. Track 10 minutes from actual hypothetical entry timestamp, not from first range candle. Frozen 3R target; suppress if risk cannot be determined without future break-candle low/high.",
    ],
  },
  {
    id: '5.5',
    number: 30,
    title: 'Moving Average Scalping Strategy',
    category: 'Scalping',
    pages: [287, 291],
    entry:
      'long: No explicitlong checklist; mirroredBUY illustration only. | short: Firsthour5m EMA5or7:2nd orlatercandle whollyaboveEMA, pendinglowbreak; updatebetterentry; laterEveningStar/dojilow example.',
    stop: 'Referencecandlehigh; eveningstarexample dojihigh.',
    target: '>=3Ror4R; nonewentriesafterfirsthour; noforcedhour-end exit specified.',
    exit: '>=3Ror4R; nonewentriesafterfirsthour; noforcedhour-end exit specified.',
    timeframe:
      '5-minute EMA **5 or 7**, trades **first hour only**, no first-candle trade. Mean reversion when price far from EMA in first 2–3 candles. p290 inspected screenshot instead displays **EMA9**: preserve inconsistency.',
    requirements: [
      '5m OHLC',
      'session open/timezone',
      'EMA5or7 choice',
      'pending non-touch candle/entry replacement state',
    ],
    notes: [
      'EMA5/7 text versusEMA9 screenshot.',
      'Only short checklist; long mirror would be local.',
      'Second candle touch does not invalidate all later first-hour setups.',
      '**Discretionary chart candidate** for short, long needs local mirror. Better-entry replacement, far criterion, evening-star geometry and EMA5 vs 7 vs 9 choice missing.',
    ],
    local: [
      'select EMA5 or 7, never silently 9; non-touch long side would require whole candle below EMA, but is local only. Stateful pending short updated to latest valid non-touch candle within hour; day2-touch must not permanently block. Hour anchored to exchange session, not clock 10:15 in all markets.',
    ],
  },
  {
    id: '5.6',
    number: 31,
    title: 'Martingale system',
    category: 'Scalping',
    pages: [292, 300],
    entry:
      'long: 1m decline ->bullishreversalhighbreak; EMA5/14 meanreversion. | short: Rally ->bearishreversallowbreak. NoEMA5cross requirement.',
    stop: 'L:greenlow; S:redhigh.',
    target: '14EMA; average1R. Lossdoubling/cap4x conflicted; signal usable separately fromsizing.',
    exit: '14EMA; average1R. Lossdoubling/cap4x conflicted; signal usable separately fromsizing.',
    timeframe:
      '1-minute,5 and 14 **EMA** in prose/checklists; p295 labels are **SMA5/SMA14**, while p298 inspected chart uses EMA5 and EMA14. Mean reversion; no explicit 5EMA crossover required in entry rules.',
    requirements: [
      '1m OHLC',
      'EMA5and14 choice',
      'manual/local reversal confirmation',
      'trade outcomes only if studying sizing; no escalation execution',
    ],
    notes: [
      'EMA prose/chart versus SMA labels p295.',
      '1x/1x/4x prose versus doubling principle and2x diagram.',
      'p300 cap4x versus early repeat-until-win explanation.',
      'p2941000+2000+3000 wrongly shown as7000.',
      '**Chart candidate for signal only; sizing discretionary/conflicted and incompatible with frozen risk**. Source cannot guarantee recovery or avoidance of loss; no complete max trades/reset/streak rule. No trail/cutoff.',
    ],
    local: [
      'retain catalog and mean-reversion guide, select EMA by checklist plus chart and disclose SMA conflict; **fixed user-risk sizing only, no automated loss escalation** in Book Patterns & Risk. Display source 4x cap/conflict informationally. Freeze 14EMA target at signal as local fixed-target handling; if 14EMA on wrong side or 1R unattainable, incomplete. Never silently change to 2R to fit other strategies.',
    ],
  },
  {
    id: '6.1',
    number: 32,
    title: 'Weekly Hedged Strategy',
    category: 'Options',
    pages: [304, 314],
    entry:
      'long: Long next-expiry CE and PE with premium slightly above corresponding current-expiry short premiums; example short 30, long 32/33. | short: Short current-expiry CE and PE whose LTP is near 2 x India VIX; premium selection defines underlying range.',
    stop: 'Close all at loss = 0.75 x maximum strategy loss; example max loss 5000, exit at -3750. This requires actual multi-leg valuation and defensible maximum-loss model.',
    target:
      'No fixed numerical target; intended theta income then longer-expiry movement exposure.',
    exit: 'Week-long lifecycle with adjustments near/beyond short strikes. Earlier conventional discussion (p307): close opposite-side near/far legs and BUY extra next-expiry directional option. Unconventional p313: on upside beyond example 18553 close puts and SELL next-expiry put matching long-call premium; symmetric downside description says sell extra call. P314 downside example instead closes calls and BUYS extra 8-Jun 18750 PE.',
    timeframe:
      'Weekly holding horizon; daily/weekly underlying charts discussed for range context.',
    requirements: [
      'India VIX',
      'option chain premiums',
      'current/next expiry calendars',
      'four contract identities and quotes/history',
      'leg sizes',
      'multi-leg P&L/max-loss model',
      'existing leg state',
    ],
    notes: [
      'Adjustment instructions conflict between p313 and p314; do not choose buy/sell silently.',
      'VIX premium matching tolerance, exact time, lot sizing, max-loss recalculation after adjustment and time-based full exit unspecified.',
      'P314 extra 18750 PE differs from original 17850 PE.',
      'Do not infer vega profit or guaranteed defined risk from source illustrations.',
    ],
    local: [],
  },
  {
    id: '6.2',
    number: 33,
    title: 'Multi Time Option Strategy',
    category: 'Options',
    pages: [315, 321],
    entry:
      'long: Not specified | short: At each schedule sell an OTM Nifty weekly CE and PE each near Rs40, one lot per side.',
    stop: 'Per-leg initial stop 2E; when option declines to half entry premium reduce stop to E (not half current premium).',
    target: 'No fixed target.',
    exit: 'All same-day trades exit by 15:15; no overnight carry.',
    timeframe: 'Intraday scheduled entries; chart bar interval absent.',
    requirements: [
      'weekly expiry metadata',
      'OTM chain selection for both sides at four slots',
      'option premium paths',
      'per-leg entry/stop state',
    ],
    notes: [
      'Premium-nearness tolerance, ties, holiday handling, repeated halving and reentry after stop unspecified.',
      'Do not combine repeated contracts into fictitious average fills.',
    ],
    local: [],
  },
  {
    id: '6.3',
    number: 34,
    title: 'Option Buying Using Open Interest',
    category: 'Options',
    pages: [322, 328],
    entry:
      'long: Monitor the selected highest-OI CE and PE; buy a contract when premium increases 10% above its 09:20 baseline. CE is bullish underlying exposure, PE bearish; both are long premiums. | short: Not specified',
    stop: 'Text says 20% of entry and example E50 risk10. Consistent risk-distance interpretation: stop = 0.8E (40), target = E + 0.4E (70). It does not mean stop-price 10.',
    target: '2R (40% premium appreciation if risk20%).',
    exit: 'First of stop, 2R target, entry+30 minutes.',
    timeframe: 'Intraday; snapshot around 09:20; holding time max 30 minutes.',
    requirements: [
      'OI chain snapshot at09:20',
      'selected CE/PE identities and expiry',
      'option premiums at baseline and after entry',
    ],
    notes: [
      'Example PE45 to50 rounds +10% (exact threshold49.5), CE15 to16.5 is exact.',
      'Expiry choice, tie breaking, whether both legs may enter and reentry rules absent.',
      'Do not replace highest-OI strike selection with price support/resistance heuristic.',
    ],
    local: [],
  },
  {
    id: '6.4',
    number: 35,
    title: 'Supertrend Selling',
    category: 'Options',
    pages: [329, 335],
    entry:
      'long: Underlying bullish bias when price closes above green Supertrend: SELL weekly ATM PE, rather than buying underlying or call. | short: Underlying bearish bias when price closes below red Supertrend: SELL weekly ATM CE.',
    stop: 'Cover sold PE on red flip; cover sold CE on green flip. No fixed premium stop.',
    target: 'No fixed target.',
    exit: 'Opposite Supertrend flip; trading stops after15:15. Full end-of-day flatten should be explicit local session convention because stop-trading language is less precise than a quoted flatten instruction.',
    timeframe: '5-minute Bank Nifty underlying chart.',
    requirements: ['weekly expiry/ATM strike metadata', 'option premiums', 'leg/fill state'],
    notes: [
      'Source Supertrend formula description is incomplete; use an identified standard implementation and disclose it.',
      '10,3 comes from indicator label; prose misleadingly calls multiplier periods3-10.',
      'Signal close timing, exact ATM rounding, lot size absent.',
    ],
    local: [
      'Use standard Supertrend ATR10 multiplier3 with Wilder smoothing, completed bars; disclose implementation choice.',
      'Render chart trend setup only; do not synthesize option premium stop or contract.',
    ],
  },
  {
    id: '6.5',
    number: 36,
    title: 'Combined Option + VWAP',
    category: 'Options',
    pages: [336, 344],
    entry:
      'long: Not specified | short: Sell both ATM Bank Nifty CE and PE together when combined premium trades at least3% below its combined-premium VWAP.',
    stop: 'Close straddle when combined premium touches VWAP.',
    target: 'No fixed target.',
    exit: 'VWAP touch; intraday strategy but exact mandatory final flatten time absent.',
    timeframe: '5-minute combined Bank Nifty ATM straddle premium chart.',
    requirements: [
      'both option premium histories',
      'common expiry/ATM contract identity',
      'combined-series volume/VWAP aggregation semantics',
      'trade counter/state',
    ],
    notes: [
      'VWAP volume source for synthetic CE+PE and whether ATM strike stays fixed after baseline are not specified.',
      'Opening prose says at open, but actual threshold gates entry.',
      'Dynamic VWAP stop does not guarantee bounded loss under gaps.',
    ],
    local: [],
  },
  {
    id: '6.6',
    number: 37,
    title: 'Momentum Buying Option',
    category: 'Options',
    pages: [345, 350],
    entry:
      'long: Buy each frozen ATM call or put independently only after its premium >=1.15 x09:30 premium. One side only or both may qualify. | short: Not specified',
    stop: '0.75E per purchased option.',
    target: '2E premium (+100%).',
    exit: 'Stop/target;15:15 time exit appears in traditional approach retained in discussion, but improved section does not restate it explicitly.',
    timeframe: 'Intraday;09:30 baseline; bar interval absent.',
    requirements: ['ATM CE/PE identities', 'expiry', '09:30 premiums and subsequent premium paths'],
    notes: [
      'Exact underlying universe, expiry choice, last entry, reentry and retained final cutoff need explicit policy.',
    ],
    local: [],
  },
  {
    id: '6.7',
    number: 38,
    title: 'The Expiry Decay Strategy',
    category: 'Options',
    pages: [351, 354],
    entry:
      'long: Not specified | short: At10:00 two days before expiry sell one lot OTM CE at rounded spot+100 and one lot OTM PE at rounded spot-100.',
    stop: 'Per-leg short buyback stop1.9E; example sell100 stop190. Source calls90 the stoploss amount, not buyback price.',
    target: 'No fixed target; premium decay intent.',
    exit: 'Stop per leg; remaining legs exit09:55 on expiry day.',
    timeframe: 'Positional; enter two days before expiry around10:00; exit expiry09:55.',
    requirements: [
      'actual expiry calendar',
      'contract strike spacing',
      'option premiums for stops',
      'India VIX for high-VIX skip',
      'leg state',
    ],
    notes: [
      'Excessively high VIX filter has no threshold.',
      'Nearest100 ties, holiday/two-days interpretation and behavior after one leg stop unspecified.',
      'Source arithmetic assumes opposite premium decays nearly to zero; do not claim guaranteed net profit.',
    ],
    local: [],
  },
  {
    id: '6.8',
    number: 39,
    title: 'The Combined Stoploss Strategy',
    category: 'Options',
    pages: [355, 358],
    entry: 'long: Not specified | short: Sell OTM call and put simultaneously at09:30.',
    stop: 'Let S0=CE_entry+PE_entry. Close both when current CE+PE >= S0+40 points; example200->240.',
    target: 'No fixed target.',
    exit: 'Combined stop or15:15 same day.',
    timeframe: 'Intraday;09:30 entry;15:15 exit.',
    requirements: [
      'option identities/selection',
      'two premium histories',
      'actual entry sum',
      'India VIX for high-VIX filter',
    ],
    notes: [
      'OTM distance/expiry/quantity missing; high-VIX skip threshold missing.',
      'Combining with a separate trend strategy is suggested but not a defined extra entry condition.',
      'Rising combined premium stop is a loss-limiting exit; source prose incorrectly implies it captures profit.',
    ],
    local: [],
  },
  {
    id: '6.9',
    number: 40,
    title: 'Exploring the Theta Decay Strategy in Options Trading',
    category: 'Options',
    pages: [359, 362],
    entry:
      'long: Not specified | short: Base:09:30 sell one ATM CE and one ATM PE. Revised preferred selection: CE and PE closestRs125; keep variant separate.',
    stop: 'Per-leg buyback stop1.25E.',
    target: 'No fixed target.',
    exit: 'Stopped leg exits; remaining/reentered positions all close15:15.',
    timeframe: 'Intraday;09:30 start;15:15 exit.',
    requirements: [
      'ATM/nearRs125 option chain and expiry',
      'option premium paths',
      'leg stop outcomes and trade counters',
    ],
    notes: [
      'Expiry, precise reentry timing, side-specific versus total3-count and option choice on reentry in revised variant unspecified.',
    ],
    local: [],
  },
  {
    id: '6.10',
    number: 41,
    title: 'Maximizing Momentum with the BTST Option Buying Strategy',
    category: 'Options',
    pages: [363, 366],
    entry:
      'long: At11:00 choose specified call, monitor fixed contract; buy when premium reaches1.2 x11:00 baseline. | short: Not specified',
    stop: '0.7E; source example reference100 -> entry120 -> stop84.',
    target: 'No fixed target.',
    exit: 'Same-day stop if hit, else next morning09:30.',
    timeframe: '11:00 reference; exit next trading morning09:30 or same-day stop.',
    requirements: [
      'option chain/strike metadata',
      '11:00 option baseline and path',
      'expiry surviving next session',
      'India VIX',
    ],
    notes: [
      'ITM/above-ATM/ATM selection contradiction; expiry choice missing.',
      'High-VIX avoidance has no threshold; last allowed entry absent.',
    ],
    local: [],
  },
  {
    id: '6.11',
    number: 42,
    title: 'The 3:00 PM Nifty Intraday Strategy',
    category: 'Options',
    pages: [367, 370],
    entry:
      'long: Not specified | short: Freeze15:00 ATM CE/PE premiums and independently sell any that falls5%. Also identify CE and PE aroundRs150 and independently short-sell on5% drop.',
    stop: 'Only premium-selected ~Rs150 legs receive short stop1.09E. Source does not put stops on ATM legs.',
    target: 'No fixed target.',
    exit: 'All legs15:29.',
    timeframe: '15:00 premium snapshots; exit15:29; bar interval absent.',
    requirements: [
      '15:00 chain ATM+nearRs150 selection',
      'four option baselines/history',
      'expiry',
      'leg entry/stop/trail state',
    ],
    notes: [
      'Overlap/duplicate-leg handling, lot proportions, expiry, reset/reentry and whether trail applies beyondRs150 set unspecified.',
      'Do not interpret prose both drop as requiring simultaneous triggers: bullets say option whose premium reduces5%.',
    ],
    local: [],
  },
  {
    id: '6.12',
    number: 43,
    title: 'The Momentum Selling Strategy',
    category: 'Options',
    pages: [371, 376],
    entry:
      'long: Not specified | short: Sell CE and/or PE independently at0.9 x10:00 premium; zero, one or both may enter, not mandatory simultaneous short straddle.',
    stop: 'Short stop1.4E per leg. If one hits stop, trail other active leg stop to its actual entry.',
    target: 'No fixed target.',
    exit: 'Individual stops; exact mandatory final intraday time absent.',
    timeframe: 'Intraday;10:00 baseline; bar interval absent.',
    requirements: [
      '10:00 ATM identities/premiums',
      'expiry',
      'two premium paths',
      'per-leg stop/entry state',
    ],
    notes: [
      'Final exit time, entry cutoff, expiry, repeated entries and no-other-leg-active adjustment behavior absent.',
    ],
    local: [],
  },
  {
    id: '6.13',
    number: 44,
    title: 'Swing Buying: A Winning Options Trading Strategy',
    category: 'Options',
    pages: [377, 381],
    entry:
      'long: Buy same-strike weekly ATM CE and PE near15:30 Thursday; both are long premium legs. | short: Not specified',
    stop: 'Initial stop0.5E each. After one stop, update survivor to half its current premium; example remaining170 -> stop85.',
    target: 'No fixed target.',
    exit: 'Stops; intended2-3-day holding horizon but exact final exit date/time absent.',
    timeframe: 'Thursday around15:30; hold2-3 days; weekly ATM straddle.',
    requirements: [
      'weekly expiry identity/calendar',
      'both premium histories',
      'India VIX',
      'leg stop outcome/state',
    ],
    notes: [
      'Entry at market close cannot be simulated as guaranteed fill.',
      '2 versus3-day choice, end-of-hold time, continuous trailing frequency and holiday handling absent.',
      'Thursday weekly expiry context may differ from actual current contracts; never infer current availability.',
    ],
    local: [],
  },
  {
    id: '7.1',
    number: 45,
    title: '9 and 21 EMA Support and Resistance Trading Strategy',
    category: 'Price action',
    pages: [384, 393],
    entry:
      'long: After consolidation, EMA9 crosses aboveEMA21; wait for resistance breakout; buy above high of breakout candle. | short: After consolidation, EMA9 crosses belowEMA21; wait for support breakdown; sell below low of breakdown candle.',
    stop: 'Long: below swing low OR low of breakout candle. Short: above swing high OR high of breakdown candle.',
    target:
      'Prior/projected resistance for long, support for short or price reversal;2R average is expectation, not universal fixed exact target.',
    exit: 'Stop or projected zone/reversal. General intro suggests moving average trailing but execution does not prescribe exact trail line/rule.',
    timeframe: '5-minute intraday chart.',
    requirements: [],
    notes: [
      'Consolidation duration/width and projected zone selection qualitative.',
      'Choose swing stop versus breakout-candle stop explicitly; no source priority.',
      'Time gap allowed between crossover and breakout, reentry and session flatten unspecified.',
    ],
    local: [
      'Use confirmed pivot/range detector shared across strategy engine, disclosed as local heuristic.',
      'Target2R may be a local fallback only; label it as proposed rather than exact source target.',
    ],
  },
  {
    id: '7.2',
    number: 46,
    title: 'Positional Trading Strategy',
    category: 'Price action',
    pages: [394, 398],
    entry:
      'long: After qualifying rally and lower-volume range, enter at high of large green high-volume breakout candle. | short: Not specified',
    stop: 'Source says minimum5% of stock range and below significant level. This is ambiguous: neither5% of entry nor5% of range has a precise definition/anchor.',
    target:
      'Ideal2R/3R; exit before historical resistance/supply. If at all-time high, pyramiding may be considered.',
    exit: 'Stop/approaching historical resistance; no fixed hold timeout.',
    timeframe: 'Daily; weeks/months/years holding.',
    requirements: [
      'enough historical OHLCV for prior significant resistance/all-time-high claim',
      'actual profitable position state for pyramiding',
    ],
    notes: [
      '15 versus20% minimum, rally window, consolidation duration, volume contraction/surge thresholds unspecified.',
      'Stop5%-of-range language ambiguous; no precise mechanical source stop can be claimed.',
      'Pyramid sizing and trail absent.',
    ],
    local: [],
  },
  {
    id: '7.3',
    number: 47,
    title: 'Pin Bar Candlestick Pattern or Reversal Strategy',
    category: 'Price action',
    pages: [399, 404],
    entry:
      'long: Bullish pin at established range support; buy range bottom with opposite resistance target. Exact candle entry trigger not stated. | short: Bearish pin at established range resistance; sell range top toward opposite support. Initial bearish pin marking range is NOT tradable; later revisit pin is count1.',
    stop: 'Risk distance may be half target distance to obtain minimum2R; source does not explicitly prescribe pin-extreme stop.',
    target: 'Opposite range boundary with minimum2R.',
    exit: 'Stop/other side of range; no fixed holding time.',
    timeframe: 'Intraday at least15 minutes; also swing.',
    requirements: [],
    notes: [
      'Small body/long wick not numerically quantified beyond bullish opposite-wick condition.',
      'Precise entry at pin close versus break of pin extreme absent; do not claim a break trigger as source fact.',
      'Range tolerance/width/count reset and exact stop anchor not specified.',
    ],
    local: [],
  },
  {
    id: '7.4',
    number: 48,
    title: 'The Pullback Strategy',
    category: 'Price action',
    pages: [405, 409],
    entry:
      'long: Wait for breakout and retest, then buy when high of pullback/retest candle breaks (p409 tip clarifies p408 wording entry at touching candle). | short: Not specified',
    stop: 'Just below long-wick retest candle low.',
    target: '3R or4R.',
    exit: 'Stop or selected3R/4R; no time exit.',
    timeframe: 'Recommended1-hour,4-hour or daily.',
    requirements: [],
    notes: [
      'No explicit bearish short mirror rules; do not label proposed short mirror as book rule.',
      'Range length, breakout size, retest tolerance and3R versus4R choice unspecified.',
    ],
    local: [],
  },
  {
    id: '7.5',
    number: 49,
    title: 'Trading Based on Repo Rate',
    category: 'Price action',
    pages: [410, 414],
    entry:
      'long: Buy Nifty50 via derivatives at announcement-day close if announced repo rate is lower than previous policy. | short: Sell Nifty50 via derivatives at announcement-day close if announced repo rate is higher.',
    stop: 'Explicitly no fixed stoploss.',
    target: 'Explicitly no fixed target.',
    exit: 'Close after one month, profit or loss.',
    timeframe:
      'Announcement-day close entry; one calendar month holding; example chart5m is not strategy requirement.',
    requirements: [
      'RBI announcement timestamp/calendar',
      'new and previous repo rates',
      'derivative identity/expiry/roll',
      'one-month trading-date convention',
    ],
    notes: [
      'Month-end/holiday handling and expiry rollover absent.',
      'No bounded stop exists in source; do not invent one and call it source stop.',
    ],
    local: [],
  },
  {
    id: '7.6',
    number: 50,
    title: 'Volatility Contraction Pattern (VCP)',
    category: 'Price action',
    pages: [415, 421],
    entry:
      'long: Buy at CLOSE of high-volume green candle breaking shared resistance after third contraction. | short: Not specified',
    stop: 'Just below third pullback low.',
    target: 'At least3R or4R.',
    exit: 'Stop or selected reward level; no time exit.',
    timeframe:
      'Positional, bigger timeframe recommended; example daily. Text says pattern can work across timeframes.',
    requirements: [],
    notes: [
      'No fixed contraction ratios, duration, resistance tolerance or volume multiplier.',
      'No explicit bearish short strategy.',
      'Source3R/4R is choice; exact selected target must be disclosed.',
    ],
    local: [],
  },
  {
    id: '7.7',
    number: 51,
    title: 'Two-Legged Pullback',
    category: 'Price action',
    pages: [422, 429],
    entry:
      'long: After HH/HL trend and second high, wait down-up-down two-legged pullback; bullish confirmation; buy above green candle high. | short: After LL/LH trend and second low, wait up-down-up pullback; bearish confirmation; sell below red candle low.',
    stop: 'Long below swing low OR bullish signal candle low. Short above swing high OR bearish signal candle high.',
    target: 'Three lots: first two at1R; final one at4R or5R after moving its stop to entry.',
    exit: 'Partial at1R then remaining stop-at-entry or4R/5R target; initial stop before1R.',
    timeframe: 'Execution1-minute or5-minute; broadly any stock/timeframe discussed.',
    requirements: ['actual entry/fills and position state for real partials or breakeven stop'],
    notes: [
      'Swing/pullback granularity qualitative; green/red confirmation only, no precise size threshold.',
      'Stop choice swing versus candle and4R versus5R target unspecified.',
      'Intrabar ordering when entry/stop/target touched on same candle cannot be resolved from OHLCV.',
    ],
    local: [
      'Use non-repainting confirmed pivots; delay recognition by pivot right-bars rather than backdating a signal.',
      'Display1R and4R as proposed reference targets if choosing default; disclose4R choice.',
    ],
  },
]
