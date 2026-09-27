import type { ResearchOptimizationReport, ResearchReport } from '@/types/trading-research'

const display = (value: number | null | undefined, suffix = '') =>
  value == null || !Number.isFinite(value)
    ? 'Unavailable'
    : `${value.toLocaleString('en-IN')}${suffix}`

export function ResearchSearchResults({ report }: { report: ResearchOptimizationReport }) {
  return (
    <section aria-label="Parameter comparison" className="space-y-3">
      <h4 className="font-medium">Parameter comparison</h4>
      <p className="text-sm text-muted-foreground">
        Compared {report.candidate_count} combinations. Candidate #{report.best_index} ranked first.
        This is exploratory selection; the final 60 sessions remain sealed. Test selected parameters
        creates a new development run before freezing.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              <th className="p-2">Candidate</th>
              <th className="p-2">Parameters</th>
              <th className="p-2">Net P&amp;L (₹)</th>
              <th className="p-2">Win rate</th>
              <th className="p-2">Trades</th>
              <th className="p-2">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {report.candidates.map((candidate) => (
              <tr className="border-t" key={candidate.index}>
                <td className="p-2">
                  #{candidate.index}
                  {candidate.index === report.best_index && ' · Selected'}
                </td>
                <td className="p-2 font-mono text-xs">
                  {Object.entries(candidate.parameters)
                    .map(([key, value]) => `${key}: ${value}`)
                    .join(', ')}
                </td>
                <td className="p-2">{display(candidate.metrics.net_pnl)}</td>
                <td className="p-2">{display(candidate.metrics.win_rate, '%')}</td>
                <td className="p-2">{candidate.metrics.trade_count}</td>
                <td className="p-2">
                  {candidate.complete ? 'Complete' : 'Incomplete — cannot promote'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function ResearchMLResults({ report }: { report: NonNullable<ResearchReport['ml']> }) {
  return (
    <section aria-label="ML evaluation" className="space-y-3 rounded-lg border p-4">
      <h4 className="font-medium">RandomForest prediction evidence</h4>
      <p className="text-sm text-muted-foreground">
        Accuracy measures labelled opportunities, including predictions to skip a trade. Trading win
        rate below measures executed trades after costs. These are different measurements.
      </p>
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <dt className="text-sm text-muted-foreground">Prediction accuracy</dt>
          <dd>{display(report.accuracy.accuracy_pct, '%')}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Majority baseline</dt>
          <dd>{display(report.accuracy.majority_baseline_pct, '%')}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Positive precision</dt>
          <dd>{display(report.accuracy.precision_pct, '%')}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Labelled opportunities</dt>
          <dd>{report.accuracy.labelled_observations}</dd>
        </div>
      </dl>
      <p className="text-sm">
        {report.accuracy.unlabelled_observations} opportunities have unavailable outcomes. They
        remain in the prediction and replay inputs.
      </p>
      <details>
        <summary className="cursor-pointer">Chronological folds and reproducibility</summary>
        <ul className="mt-2 space-y-1 text-sm">
          {report.cross_validation.model_metadata.folds_report.map((fold) => (
            <li key={fold.fold}>
              Fold {fold.fold}: {fold.train_observations} training / {fold.validation_observations}{' '}
              validation opportunities · accuracy {display(fold.accuracy.accuracy_pct, '%')}
            </li>
          ))}
        </ul>
        <p className="mt-2 break-all font-mono text-xs">Fitted model: {report.model_hash}</p>
        <p className="break-all font-mono text-xs">Predictions: {report.prediction_hash}</p>
      </details>
      {report.diagnostics && (
        <details>
          <summary className="cursor-pointer">Prediction quality and feature importance</summary>
          <p className="mt-2 text-sm">
            Brier loss: {display(report.diagnostics.brier_score)} · Training baseline:{' '}
            {display(report.diagnostics.baseline_brier_score)}. Lower is better. These diagnostics
            use the evaluation period; they do not certify profitability.
          </p>
          {report.diagnostics.baseline_difference_95 && (
            <p className="text-sm">
              Model minus baseline, 95% session-block interval:{' '}
              {display(report.diagnostics.baseline_difference_95.lower_95)} to{' '}
              {display(report.diagnostics.baseline_difference_95.upper_95)}. Negative favors the
              model.
            </p>
          )}
          <ul className="mt-2 text-sm">
            {Object.entries(report.artifact?.feature_importance ?? {})
              .sort((a, b) => b[1] - a[1])
              .slice(0, 10)
              .map(([name, value]) => (
                <li key={name}>
                  {name}: {display(Math.round(value * 10000) / 100, '%')}
                </li>
              ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Training impurity importance is descriptive and may favor correlated features.
          </p>
          <table className="mt-2 w-full text-left text-sm">
            <caption className="text-left">
              Probability calibration on evaluated opportunities
            </caption>
            <thead>
              <tr>
                <th>Predicted</th>
                <th>Observed wins</th>
                <th>Observations</th>
              </tr>
            </thead>
            <tbody>
              {report.diagnostics.reliability.map((bin, i) => (
                <tr key={`${bin.mean_prediction}-${i}`}>
                  <td>{display(Math.round(bin.mean_prediction * 100), '%')}</td>
                  <td>{display(Math.round(bin.mean_actual * 100), '%')}</td>
                  <td>{bin.observations}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <p className="text-sm font-medium">{report.deployment_reason}</p>
    </section>
  )
}
