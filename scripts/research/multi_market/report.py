"""Self-contained, printable research report; no CDN or account data."""

import html
import json


def render(result, out):
    esc = html.escape

    def pf(v):
        return (
            f"{v['profit_factor']:.2f}"
            if v["profit_factor"] is not None
            else ("∞ (no losses)" if v["wins"] and v["net"] > 0 else "—")
        )

    def win(v):
        return f"{100 * v['win_rate']:.1f}%" if v["trades"] else "No trades"

    rows = []
    details = []
    for symbol, m in result["markets"].items():
        f = m["final"]
        c = m["candidate"]
        cv = result["coverage"][symbol]
        verdict = "Passed research screen" if m["meets_research_screen"] else "Not qualified"
        rows.append(
            f"<tr><th>{symbol}</th><td>{cv['sessions']}</td><td>{f['trades']}</td><td>{win(f)}</td><td>{f['net']:+.2f}</td><td>{pf(f)}</td><td>{verdict}</td></tr>"
        )
        stages = "".join(
            f"<tr><th>{title}</th><td>{v['trades']}</td><td>{win(v)}</td><td>{v['net']:+.3f}</td><td>{v['expectancy']:+.4f}</td><td>{pf(v)}</td><td>{v['drawdown']:.3f}</td><td>{v['unresolved']}</td></tr>"
            for title, v in [
                ("Development", m["development"]),
                ("Validation", m["validation"]),
                ("Final test", f),
                ("Final, stress costs", m["stress"]),
            ]
        )
        periods = " · ".join(
            f"{k}: {v['first']} to {v['last']} ({v['sessions']} days)"
            for k, v in m["split"].items()
        )
        details.append(f'''<section><h2>{symbol} <small>{verdict}</small></h2>
<p><strong>{esc(m["id"])}</strong></p><p>Values in {esc(m["unit"])}. {"Selected for diagnostic comparison only; development/validation requirements failed." if m["diagnostic_only"] else "Selected from development and validation before final-test evaluation."}</p>
<p class="muted">{periods}</p><div class="scroll"><table><thead><tr><th>Period</th><th>Trades</th><th>Wins</th><th>Net</th><th>Avg / trade</th><th>Profit factor</th><th>Drawdown</th><th>Unresolved</th></tr></thead><tbody>{stages}</tbody></table></div>
<p>{"No final trades: interval and average P&amp;L below are not meaningful. " if not f["trades"] else ""}Final win-rate descriptive 95% interval: {100 * f["win_interval"][0]:.1f}–{100 * f["win_interval"][1]:.1f}%. Average win {f["average_win"]:.3f}; average loss {f["average_loss"]:.3f}. Reward {c["reward"]:g}R against stop {c["stop_atr"]:g} ATR; hold up to {c["hold_minutes"]} minutes.</p>
<p>{"Insufficient final-period length: at three trades a day, this split permits at most " + str(m["split"]["test"]["sessions"] * 3) + " entries, below the predeclared 100-trade evidence threshold." if m["split"]["test"]["sessions"] * 3 < 100 else "The final sample must still reach the predeclared 100-trade threshold."}</p>
<p>Coverage: {cv["usable_rows"]:,} usable 1-minute candles; {cv["invalid_or_repaired"]:,} invalid/repaired and {cv["out_of_session"]:,} out-of-session rows excluded. {cv["missing_minutes_within_observed_sessions"]:,} missing minutes versus full observed sessions (includes partial boundary days).</p>
<p><a href="{symbol}-development.csv">All 600 development results</a> · <a href="{symbol}-final-trades.csv">Final trades</a> · <a href="{symbol}-selection.json">Frozen selection</a></p></section>''')
    options = ""
    if "options" in result:
        options = "<section><h2>Actual option-premium diagnostic</h2>"
        for sym, o in result["options"].items():
            options += f"<h3>{sym}</h3><p>{esc(o['status'])}</p>"
            if "summary" in o:
                s = o["summary"]
                options += f'<p>{s["trades"]} resolved trades · {100 * s["win_rate"]:.1f}% net wins · Net ₹{s["net"]:.2f} · fees ₹{s["fees"]:.2f} · unresolved {s["unresolved"]}. <a href="{sym}-option-trades.csv">Trade records</a></p>'
            options += f'<p class="muted">{esc(json.dumps(o.get("skips", {})))}</p>'
        options += "</section>"
    source_links = "".join(
        f'<li><a href="{esc(url)}">{esc(title)}</a></li>' for title, url in result["sources"]
    )
    limits = "".join(f"<li>{esc(x)}</li>" for x in result["limitations"])
    body = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Four-market strategy research — 17 October 2026</title>
<style>:root{{color-scheme:light}}body{{margin:0;background:#f4f5f7;color:#172334;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:40px 24px}}h1{{font-size:34px;line-height:1.15;margin:12px 0}}h2{{font-size:24px;margin:0 0 16px}}h3{{font-size:18px}}small,.muted{{color:#536171}}small{{font-size:14px;font-weight:500}}section{{background:white;border:1px solid #dce0e5;border-radius:12px;padding:26px;margin:22px 0}}.lead{{max-width:850px}}.notice{{border-left:4px solid #a75c00;background:#fff7e8;padding:16px 20px}}table{{width:100%;border-collapse:collapse;text-align:left;font-variant-numeric:tabular-nums;font-size:14px}}th,td{{padding:12px 10px;border-bottom:1px solid #e4e8ed;white-space:nowrap}}thead{{background:#edf1f5}}a{{color:#175c9d}}.scroll{{overflow:auto}}li{{margin-bottom:9px}}.tag{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#536171}}@media print{{body{{background:white;font-size:11px}}main{{padding:0}}section{{break-inside:avoid}}a{{text-decoration:none;color:inherit}}h1{{font-size:25px}}}}</style>
<main><div class="tag">17 October 2026 · research version chart-combinations-v1</div><h1>Can a chart combination sustain 80% wins?</h1><p class="lead">2,400 fixed combinations across BTCUSD, NIFTY, BANKNIFTY and SENSEX. Rules use completed candles, at most three entries per day, and a chronological development → validation → final-test process.</p>
<p class="notice"><strong>{sum(m["meets_research_screen"] for m in result["markets"].values())} of 4 selected candidates passed the full research screen.</strong> A high development win rate is not evidence of future performance. Indian index results below are measured in points and do not represent CE/PE profitability.</p>
<section><h2>Final test comparison</h2><div class="scroll"><table><thead><tr><th>Market</th><th>History days</th><th>Final trades</th><th>Net wins*</th><th>Net*</th><th>Profit factor</th><th>Decision</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div><p class="muted">*BTC: USD after estimated trading costs and funding reserve. Indian indices: directional points after assumed slippage, before derivative-specific costs. They are different measures and must not be added or ranked by absolute P&amp;L.</p></section>
<section><h2>Our strategy families</h2><ol><li><strong>Trend pullback:</strong> EMA20/50 trend and EMA20 slope, ADX strength, pullback to EMA20 and directional candle close.</li><li><strong>Breakout retest:</strong> close beyond the preceding 20-bar extreme by 0.1 ATR, then first successful retest within three bars; the level is frozen.</li><li><strong>Range reclaim:</strong> previous close outside Bollinger20/2, current close back inside, ADX below 20.</li><li><strong>Range sweep reversal:</strong> wick beyond the previous 20-bar extreme, close back inside with a matching reversal candle.</li><li><strong>Regime combination:</strong> trend pullback/retest during a trend; range reclaim/sweep when ADX is below 20.</li></ol><p>Selective variants add RSI, volatility and candle-size checks, plus traded-volume confirmation for BTC only. No index volume is invented.</p><p>Search: 5/15-minute bars × base/selective × 1/1.5/2.5 ATR stop × 0.5/1/1.5/2/3R target × 30/120-minute holding limit. A 0.5R target wins less than it risks.</p></section>
{"".join(details)}{options}<section><h2>What qualifies?</h2><p>Final win rate ≥80%, at least 100 final trades, positive expectancy, profit factor ≥1.2, positive net result with doubled costs, no unresolved trades and at least 60 observed history days. A pass would still require forward validation. Small samples can produce 80–100% by chance.</p><p>Development candidates require ≥30 trades and positive expectancy; at most ten reach validation. Final results never select a replacement candidate.</p></section>
<section><h2>Evidence and limits</h2><ul>{limits}</ul></section><section><h2>Research sources</h2><p>These explain chart concepts and testing methods. They do not validate this app's thresholds or claim an 80% strategy. This is a representative source review, not every strategy on the internet.</p><ul>{source_links}</ul><p><a href="results.json">Full machine-readable report</a> · <a href="data/coverage.json">Data coverage and checksums</a></p></section></main></html>"""
    (out / "report.html").write_text(body)
