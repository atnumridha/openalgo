import { cryptoChartPattern } from './cryptoChartPatterns'
type Side = 'CALL' | 'PUT' | 'NEUTRAL'
// Plain-language descriptions. Direction always comes from the confirmed detector,
// including bilateral chart shapes; the name alone must never override it.
// References: StockCharts ChartSchool candlestick and chart-pattern guides.
const meanings: [RegExp, string][] = [
  [
    /inverted hammer/i,
    'A small candle body has a long upper wick. Buyers pushed up, but could not hold all of the rise. A later upward close is needed to support a reversal.',
  ],
  [
    /shooting star|gravestone/i,
    'Price pushed higher, then fell back before the candle closed. The long upper wick shows rejection of higher prices.',
  ],
  [
    /hanging man/i,
    'A small candle body with a long lower wick appears after a rise. Selling pressure may be increasing.',
  ],
  [
    /hammer|dragonfly/i,
    'Price dropped, then recovered before the close. The long lower wick shows rejection of lower prices.',
  ],
  [
    /pin bar|wick rejection/i,
    'A long wick shows that price tried one direction and was pushed back. The confirmed move is away from that rejected area.',
  ],
  [
    /last engulfing/i,
    'An engulfing candle appears near a possible trend ending. The following confirmed move points to a possible reversal.',
  ],
  [
    /engulf/i,
    'A larger candle body covers the previous candle body. Pressure has shifted toward the direction of the confirming move.',
  ],
  [
    /harami/i,
    'A smaller candle body sits inside the previous larger body. The earlier move has slowed; the confirming close gives the direction.',
  ],
  [
    /piercing|dark cloud/i,
    'The next candle closes well back inside the previous candle body. The earlier move is losing control and may reverse.',
  ],
  [
    /morning|evening|abandoned baby|island reversal|tri.star/i,
    'A strong move pauses around a small candle or gap, then price moves the other way. This can mark a change in direction.',
  ],
  [
    /marubozu|belt hold|long line/i,
    'A strong candle closes near one end of its range. Buyers or sellers controlled most of that candle.',
  ],
  [
    /doji|spinning top|high wave|rickshaw|short line/i,
    'The candle shows hesitation: price moved around but neither side gained clear control. Its shape alone does not choose a direction.',
  ],
  [
    /tweezer|matching high|matching low|counterattack|meeting lines/i,
    'Nearby candles test a similar price level. A confirmed move away from that level may show a turn.',
  ],
  [
    /soldiers|crows|three inside|three outside|three.line strike/i,
    'Several candles form a sequence showing a shift in buying or selling pressure. The completed confirmation gives the direction.',
  ],
  [
    /three methods|mat hold|tasuki|gap three|separating|side.by.side|gapping|window|on neck|in neck|thrusting/i,
    'Price pauses or gaps during a move. A confirmed move beyond the pause can show that the earlier direction is continuing.',
  ],
  [
    /advance block|deliberation/i,
    'Successive candles make less progress. The earlier move may be weakening.',
  ],
  [
    /nr4|narrow range/i,
    'One completed candle has a smaller range than each of the preceding three. A later close outside its high or low confirms the observed expansion direction.',
  ],
  [
    /pipe bottom|pipe top/i,
    'Two unusually wide candles reverse the preceding move near a matching extreme. A later close through the second candle boundary confirms the reversal observation.',
  ],
  [
    /inside bar/i,
    'This candle stays within the previous candle range. Price is pausing; a break out of the range gives direction.',
  ],
  [
    /outside bar/i,
    'This candle extends beyond both ends of the previous range. Price is volatile; the confirmed close gives direction.',
  ],
  [
    /head.*shoulder|quasimodo/i,
    'Price makes several swings, then breaks or retests a key level. This can mark a reversal of the earlier trend.',
  ],
  [
    /double|triple|\b[wm] (shape|bottom|top)/i,
    'Price tests a similar turning area two or three times, then breaks the level between the tests. This may mark a trend reversal.',
  ],
  [
    /cup|rounding|scallop/i,
    'Price turns through a rounded base or top. Breaking the edge of the shape may start a move in the confirmed direction.',
  ],
  [
    /triangle|pennant/i,
    'Price swings into a narrowing range. The direction comes from the completed breakout; the shape can break either way.',
  ],
  [
    /wedge/i,
    'Two sloping boundaries move closer together. A completed close outside the wedge can signal a new move.',
  ],
  [
    /flag|measured move/i,
    'A strong move is followed by a pause or pullback. A confirmed break may start another move in the same direction.',
  ],
  [
    /rectangle|channel|range|compression|repeated level/i,
    'Price trades between boundaries. A completed break outside the range may start a new move; a return inside weakens it.',
  ],
  [
    /three rising valleys|three descending peaks/i,
    'Three successive swings step higher or lower. A confirmed break beyond the intervening swings supports that direction.',
  ],
  [
    /diamond|broadening/i,
    'The swings first spread out, then tighten or break a boundary. The completed break gives the possible next direction.',
  ],
  [
    /parabolic sar/i,
    'The trailing Parabolic SAR level switches sides of price. This can signal a direction change, but sideways markets can produce repeated flips.',
  ],
  [
    /sweep|rejection|retest|s\/r flip|swing.*break|slingshot/i,
    'Price tests a support or resistance level, then closes away from it. A broken level holding on a retest supports the new direction.',
  ],
  [
    /wolfe|three.drive/i,
    'Several alternating swings form a turning structure. A confirmed break or reclaim can signal a reversal.',
  ],
  [
    /bottom|top|river|ladder|swallow|pigeon|hawk|sandwich|stomach|breakaway|new price/i,
    'A sequence of candles shows a possible change in buying or selling pressure. The completed confirmation gives the direction.',
  ],
]
export function patternExplanation(name: string, side: Side, pattern?: string): string {
  const meaning =
    cryptoChartPattern(pattern ?? '')?.meaning ??
    meanings.find(([rule]) => rule.test(name))?.[1] ??
    'This candle sequence or price structure matched the chart rules. The completed confirmation gives the direction.'
  const next =
    side === 'CALL'
      ? 'Price may rise if buying continues.'
      : side === 'PUT'
        ? 'Price may fall if selling continues.'
        : 'No clear direction. Wait for a confirmed move.'
  const context = /at demand/i.test(name)
    ? '\nAt demand: price bounced from a previously tested support area.'
    : /at supply/i.test(name)
      ? '\nAt supply: price fell away from a previously tested resistance area.'
      : ''
  return `${name}\n${meaning}${context}\nWhat may happen: ${next}\nA pattern can fail. An old label describes that candle, not a fresh entry now.`
}
