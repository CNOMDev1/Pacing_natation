import SwiftUI
import Charts

/// Graphique couloir : bandes percentiles + médiane + courbes nageurs.
///
/// L’axe Y affiche les secondes avec le meilleur temps en haut. Les valeurs
/// tracées sont `-temps` pour que Swift Charts remplisse des rubans continus
/// (un domaine Y inversé `[max, min]` produit des triangles disjoints).
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
                ribbon(from: \.p10, to: \.p25, series: "P10–P25", color: PacingTheme.belowMedianOuter)
                ribbon(from: \.p25, to: \.p50, series: "P25–P50", color: PacingTheme.belowMedianInner)
                ribbon(from: \.p50, to: \.p75, series: "P50–P75", color: PacingTheme.aboveMedianInner)
                ribbon(from: \.p75, to: \.p90, series: "P75–P90", color: PacingTheme.aboveMedianOuter)
                medianLine
                swimmerAContent
                swimmerBContent
            }
            .chartXScale(domain: xDomain)
            .chartYScale(domain: yDomain)
            .chartYAxis {
                AxisMarks(position: .leading) { value in
                    AxisGridLine()
                    AxisValueLabel {
                        if let plotted = value.as(Double.self) {
                            Text(TimeFormat.seconds(-plotted))
                                .font(.caption2)
                        }
                    }
                }
            }
            .chartXAxisLabel("Âge (années)")
            .chartYAxisLabel("Temps (s)")
            .chartLegend(.hidden)
            .frame(minHeight: 280)
            .padding(12)
            .background(PacingTheme.canvas)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            legend
        }
    }

    @ChartContentBuilder
    private func ribbon(
        from lower: KeyPath<CorridorBand, Double?>,
        to upper: KeyPath<CorridorBand, Double?>,
        series: String,
        color: Color
    ) -> some ChartContent {
        ForEach(sortedBands) { band in
            if let lo = band[keyPath: lower], let hi = band[keyPath: upper] {
                AreaMark(
                    x: .value("Âge", band.xValue),
                    yStart: .value("Bas", plotY(lo)),
                    yEnd: .value("Haut", plotY(hi)),
                    series: .value("Bande", series)
                )
                .foregroundStyle(color)
                .interpolationMethod(.linear)
            }
        }
    }

    @ChartContentBuilder
    private var medianLine: some ChartContent {
        ForEach(sortedBands) { band in
            if let p50 = band.p50 {
                LineMark(
                    x: .value("Âge", band.xValue),
                    y: .value("Temps", plotY(p50)),
                    series: .value("Série", "Médiane")
                )
                .foregroundStyle(PacingTheme.median)
                .lineStyle(StrokeStyle(lineWidth: 2.4, lineCap: .round))
                .interpolationMethod(.linear)
            }
        }
    }

    @ChartContentBuilder
    private var swimmerAContent: some ChartContent {
        if let swimmerA {
            swimmerSeries(swimmerA, dashed: false, color: PacingTheme.swimmerA)
        }
    }

    @ChartContentBuilder
    private var swimmerBContent: some ChartContent {
        if let swimmerB {
            swimmerSeries(swimmerB, dashed: true, color: PacingTheme.swimmerB)
        }
    }

    @ChartContentBuilder
    private func swimmerSeries(_ swimmer: CorridorSwimmer, dashed: Bool, color: Color) -> some ChartContent {
        ForEach(swimmer.points) { point in
            LineMark(
                x: .value("Âge", point.xValue),
                y: .value("Temps", plotY(point.timeS)),
                series: .value("Série", swimmer.name)
            )
            .foregroundStyle(color)
            .lineStyle(StrokeStyle(lineWidth: 2.5, dash: dashed ? [5, 3] : []))
            .interpolationMethod(.linear)

            PointMark(
                x: .value("Âge", point.xValue),
                y: .value("Temps", plotY(point.timeS))
            )
            .foregroundStyle(color)
            .symbolSize(40)
        }
    }

    private var sortedBands: [CorridorBand] {
        bands.sorted { $0.xValue < $1.xValue }
    }

    private func plotY(_ seconds: Double) -> Double { -seconds }

    private var xDomain: ClosedRange<Double> {
        let xs = sortedBands.map(\.xValue)
            + (swimmerA?.points.map(\.xValue) ?? [])
            + (swimmerB?.points.map(\.xValue) ?? [])
        return closedRange(from: xs, fallback: 0...1)
    }

    private var yDomain: ClosedRange<Double> {
        var ys: [Double] = []
        for band in sortedBands {
            ys.append(contentsOf: [band.p10, band.p25, band.p50, band.p75, band.p90].compactMap { $0 })
        }
        ys.append(contentsOf: swimmerA?.points.map(\.timeS) ?? [])
        ys.append(contentsOf: swimmerB?.points.map(\.timeS) ?? [])
        let range = closedRange(from: ys, fallback: 0...1)
        return plotY(range.upperBound)...plotY(range.lowerBound)
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
            legendItem(color: PacingTheme.belowMedianOuter, text: "P10–P25")
            legendItem(color: PacingTheme.belowMedianInner, text: "P25–P50")
            legendItem(color: PacingTheme.median, text: "Médiane")
            legendItem(color: PacingTheme.aboveMedianInner, text: "P50–P75")
            legendItem(color: PacingTheme.aboveMedianOuter, text: "P75–P90")
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
