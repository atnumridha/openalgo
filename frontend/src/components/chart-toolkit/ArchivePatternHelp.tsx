import {
  TRADINGVIEW_CHART_PATTERNS,
  TRADINGVIEW_PATTERN_SOURCE,
} from './tradingViewPatternCoverage'
import { CRYPTO_CHART_PATTERNS } from './cryptoChartPatterns'
import { INSTITUTIONAL_PATTERN_CATALOG } from './archiveInstitutionalPatterns'
const groups = [
  [
    'Candle shapes',
    'Hammer, Inverted Hammer, Hanging Man, Shooting Star, two-candle Shooting Star, Engulfing, Harami, Harami Cross, Piercing, Dark Cloud, Marubozu, Belt Hold, Pin Bar, Doji, Dragonfly, Gravestone, Long Legged Doji, Rickshaw Man, Northern / Southern Doji, High Wave, Spinning Top, Long / Short Line, Inside / Outside Bar',
  ],
  [
    'Candle combinations',
    'Morning / Evening Star, Doji Star, Morning / Evening Doji Star, Abandoned Baby, Island Reversal, Tweezers, Soldiers / Crows, Identical Crows, Three Inside / Outside, Three-Line Strike, Rising / Falling Three Methods, Mat Hold, Breakaway, Advance Block, Deliberation, Concealing Baby Swallow, Homing Pigeon, Matching High / Low, Counterattack / Meeting Lines, Separating Lines, In Neck, On Neck, Thrusting, Stick Sandwich, Ladder Bottom / Top, Three Stars in South / North, Unique Three River, Tri-Star, Last Engulfing, Above / Below Stomach, 8 / 10 / 12 / 13 New Price Lines',
  ],
  [
    'Gaps and windows',
    'Tasuki Gap, Gap Three Methods, Upside Gap Two Crows, Two Crows, Side-by-side White Lines, Two Black Gapping, Gapping Doji, Collapsing Doji Star, Rising / Falling Window',
  ],
  [
    'Chart shapes',
    'Double / Triple Top and Bottom, W / M shapes, Head and Shoulders, Inverse Head and Shoulders, Ascending / Descending / Symmetrical Triangle, Flags, Pennants, Rectangles, Rising / Falling Wedge, Broadening Wedge, Channels, Cup and Handle, Inverse Cup and Handle, Rounding Top / Bottom, Ascending / Descending Scallop, Three Rising Valleys / Descending Peaks, Measured Move Up / Down, Diamond Bottom / Top, V Bottom / Top, Slingshot, Wolfe Wave',
  ],
  [
    'Confirmed setups',
    'Candles confirmed at demand / supply, swing break and retest, Quasimodo retests, S/R flip, sweep rejection, compression breakout, repeated level break, three-drive reversal, compressed range breakout, expanding-contracting range breakout, flag limit retest, Parabolic SAR flip',
  ],
] as const
export function ArchivePatternHelp({ crypto = false }: { crypto?: boolean }) {
  return (
    <details className="border-t pt-2">
      <summary className="cursor-pointer font-medium text-foreground">Archive coverage</summary>
      <div className="space-y-3 pt-2">
        <p>
          Archive images and the five trend-reference sheets checked. Repeated patterns are
          combined.
        </p>
        {crypto && (
          <details>
            <summary className="cursor-pointer text-foreground">
              Crypto chart patterns · 15 active
            </summary>
            <p className="pt-1">
              These run on the selected crypto symbol and timeframe. Names appear after a completed
              breakout. The newest visible matching formation gets an outline; its direction follows
              the breakout. Dotted arrows connect labels to candles.
            </p>
            <ul className="space-y-2 pt-2">
              {CRYPTO_CHART_PATTERNS.map((pattern) => (
                <li key={pattern.name}>
                  <span className="text-foreground">{pattern.name}</span> — {pattern.meaning}
                </li>
              ))}
            </ul>
            <a
              className="mt-2 inline-block underline"
              href="https://fomo.family/blog/learn/crypto-chart-patterns-the-15-patterns-that-actually-matter"
              target="_blank"
              rel="noreferrer"
            >
              Reference article
            </a>
          </details>
        )}
        {crypto && (
          <details>
            <summary className="cursor-pointer text-foreground">
              TradingView cheat sheet · 20 covered
            </summary>
            <p className="pt-1">
              Uses the same indicator. Patterns listed above are reused; additional names are below.
              Gartley/Cypher need Fibonacci ratios and a confirmed reversal. Livermore uses
              documented expanding-range geometry.
            </p>
            <ul className="space-y-2 pt-2">
              {TRADINGVIEW_CHART_PATTERNS.filter(
                (p) => !CRYPTO_CHART_PATTERNS.some((existing) => existing.name === p.name)
              ).map((p) => (
                <li key={p.name}>
                  <span className="text-foreground">{p.name}</span> — {p.meaning}
                </li>
              ))}
            </ul>
            <a
              href={TRADINGVIEW_PATTERN_SOURCE}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block underline"
            >
              TradingView cheat sheet
            </a>
          </details>
        )}
        {groups.map(([name, items]) => (
          <details key={name}>
            <summary className="cursor-pointer text-foreground">{name}</summary>
            <p className="pt-1">{items}</p>
          </details>
        ))}
        <details>
          <summary className="cursor-pointer text-foreground">Corrections to the images</summary>
          <p className="pt-1">
            On-Neck is bearish continuation. Falling Three Methods is bearish. Upside Gap Two Crows
            is bearish. A Spinning Top or Doji alone has no clear direction. Three Black Crows is
            the bearish name used for the image labelled “Three White Soldier” at supply. Chart
            direction follows the completed breakout, not a printed BUY or SELL caption. Triangles
            can break either way. A rounded cup needs a handle; a sharp V does not count as a cup.
            Measured targets are estimates.
          </p>
        </details>
        <details>
          <summary className="cursor-pointer text-foreground">
            Names from the institutional sheet
          </summary>
          <ul className="space-y-2 pt-1">
            {INSTITUTIONAL_PATTERN_CATALOG.map((item) => (
              <li key={item.name}>
                <span className="text-foreground">{item.name}</span>
                {' — '}
                {item.status === 'unsupported'
                  ? 'Reference only: this sketch does not define a distinct rule.'
                  : item.status === 'partial-operational'
                    ? 'Uses the matching break, retest or range setup; exact special rules are not shown in the image.'
                    : 'Uses clearly defined chart geometry.'}
              </li>
            ))}
          </ul>
        </details>
        <p>
          Dock Wave, TheFich, Ticksban and clock-only London / New York captions do not define
          reliable separate signals. Their visible candle and range shapes are covered by the
          standard detectors. Stars in the images are not measured probabilities.
        </p>
        <p>
          These are shape rules, not measured win rates. Pattern settings use documented
          definitions; a matching sketch does not prove buying or selling by institutions.
        </p>
      </div>
    </details>
  )
}
