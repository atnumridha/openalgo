import type { IChartApi, Time } from 'lightweight-charts'

function historyPoint(point: { time: Time; value?: number; open?: number }) {
  const time = point.time
  return {
    time: typeof time === 'object'
      ? `${time.year}-${time.month}-${time.day}`
      : `${typeof time}:${time}`,
    valued: point.value !== undefined || point.open !== undefined,
  }
}

/** Keep crosshair hit testing out of partially replaced multi-series history. */
export function protectChartHistoryRefresh(chart: IChartApi): void {
  const addSeries = chart.addSeries.bind(chart)
  chart.addSeries = ((definition, options, paneIndex) => {
    const series = addSeries(definition, options, paneIndex)
    const setData = series.setData.bind(series)
    const update = series.update.bind(series)
    let previousPoints: ReturnType<typeof historyPoint>[] | null = []
    series.setData = (data) => {
      const points = data.map(historyPoint)
      const previous = previousPoints
      // History can change logical indexes shared by every indicator series.
      // The next pointer movement restores hover after this synchronous update.
      if (previous === null || points.length !== previous.length || points.some((point, i) =>
        point.time !== previous[i].time || point.valued !== previous[i].valued
      )) {
        chart.clearCrosshairPosition()
      }
      setData(data)
      previousPoints = points
    }
    series.update = (data, historicalUpdate) => {
      update(data, historicalUpdate)
      if (previousPoints === null) return
      const point = historyPoint(data)
      const last = previousPoints.length - 1
      if (previousPoints[last]?.time === point.time) previousPoints[last] = point
      else if (!historicalUpdate) previousPoints.push(point)
      else {
        const index = previousPoints.findIndex(previous => previous.time === point.time)
        if (index >= 0) previousPoints[index] = point
        else previousPoints = null // Unusual historical insertion: clear on the next replacement.
      }
    }
    return series
  }) as typeof chart.addSeries
}
