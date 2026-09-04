import SwiftUI
import Charts

/// Graphique couloir : bandes percentiles + médiane + courbes nageurs.
struct CorridorChartView: View {
    let bands: [CorridorBand]
    var swimmerA: CorridorSwimmer? = nil
    var swimmerB: CorridorSwimmer? = nil
    var title: String = "Couloir de performance"

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.headline)

            Chart {
                ForEach(bands) { band in
                    if let p10 = band.p10, let p90 = band.p90 {
                        AreaMark(
                            x: .value("Âge", band.xValue),
                            yStart: .value("p10", p10),
                            yEnd: .value("p90", p90)
                        )
                        .foregroundStyle(PacingTheme.bandOuter)
                        .interpolationMethod(.catmullRom)
                    }
                    if let p25 = band.p25, let p75 = band.p75 {
                        AreaMark(
                            x: .value("Âge", band.xValue),
                            yStart: .value("p25", p25),
                            yEnd: .value("p75", p75)
                        )
                        .foregroundStyle(PacingTheme.bandInner)
                        .interpolationMethod(.catmullRom)
                    }
                    if let p50 = band.p50 {
                        LineMark(
                            x: .value("Âge", band.xValue),
                            y: .value("Médiane", p50)
                        )
                        .foregroundStyle(PacingTheme.median)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                        .interpolationMethod(.catmullRom)
                    }
                }

                if let swimmerA {
                    ForEach(swimmerA.points) { point in
                        LineMark(
                            x: .value("Âge", point.xValue),
                            y: .value("Temps", point.timeS),
                            series: .value("Série", swimmerA.name)
                        )
                        .foregroundStyle(PacingTheme.swimmerA)
                        .lineStyle(StrokeStyle(lineWidth: 2.5))
                        .interpolationMethod(.catmullRom)

                        PointMark(
                            x: .value("Âge", point.xValue),
                            y: .value("Temps", point.timeS)
                        )
                        .foregroundStyle(PacingTheme.swimmerA)
                        .symbolSize(40)
                    }
                }

                if let swimmerB {
                    ForEach(swimmerB.points) { point in
                        LineMark(
                            x: .value("Âge", point.xValue),
                            y: .value("Temps", point.timeS),
                            series: .value("Série", swimmerB.name)
                        )
                        .foregroundStyle(PacingTheme.swimmerB)
                        .lineStyle(StrokeStyle(lineWidth: 2.5, dash: [5, 3]))
                        .interpolationMethod(.catmullRom)

                        PointMark(
                            x: .value("Âge", point.xValue),
                            y: .value("Temps", point.timeS)
                        )
                        .foregroundStyle(PacingTheme.swimmerB)
                        .symbolSize(40)
                    }
                }
            }
            .chartXScale(domain: xDomain)
            .chartYScale(domain: yDomain)
            .chartYAxis {
                AxisMarks(position: .leading) { value in
                    AxisGridLine()
                    AxisValueLabel {
                        if let seconds = value.as(Double.self) {
                            Text(TimeFormat.mmss(seconds))
                                .font(.caption2)
                        }
                    }
                }
            }
            .chartXAxisLabel("Âge (années)")
            .chartYAxisLabel("Temps")
            .frame(minHeight: 280)
            .padding(12)
            .background(PacingTheme.canvas)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            legend
        }
    }

    /// Bornes X = min/max des âges présents (bandes + nageurs).
    private var xDomain: ClosedRange<Double> {
        let xs = bands.map(\.xValue)
            + (swimmerA?.points.map(\.xValue) ?? [])
            + (swimmerB?.points.map(\.xValue) ?? [])
        return closedRange(from: xs, fallback: 0...1)
    }

    /// Bornes Y = min/max des temps, inversées (meilleur temps en haut).
    /// Un tableau `[max, min]` inverse l’axe tout en le calant sur les données.
    private var yDomain: [Double] {
        var ys: [Double] = []
        for band in bands {
            ys.append(contentsOf: [band.p10, band.p25, band.p50, band.p75, band.p90].compactMap { $0 })
        }
        ys.append(contentsOf: swimmerA?.points.map(\.timeS) ?? [])
        ys.append(contentsOf: swimmerB?.points.map(\.timeS) ?? [])
        let range = closedRange(from: ys, fallback: 0...1)
        return [range.upperBound, range.lowerBound]
    }

    private func closedRange(from values: [Double], fallback: ClosedRange<Double>) -> ClosedRange<Double> {
        guard let minV = values.min(), let maxV = values.max() else { return fallback }
        if minV == maxV {
            let pad = max(abs(minV) * 0.05, 0.5)
            return (minV - pad)...(maxV + pad)
        }
        return minV...maxV
    }

    private var legend: some View {
        HStack(spacing: 16) {
            legendItem(color: PacingTheme.bandOuter, text: "p10–p90")
            legendItem(color: PacingTheme.bandInner, text: "p25–p75")
            legendItem(color: PacingTheme.median, text: "Médiane")
            if let swimmerA {
                legendItem(color: PacingTheme.swimmerA, text: swimmerA.name)
            }
            if let swimmerB {
                legendItem(color: PacingTheme.swimmerB, text: swimmerB.name)
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func legendItem(color: Color, text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 2)
                .fill(color)
                .frame(width: 12, height: 12)
            Text(text)
        }
    }
}
