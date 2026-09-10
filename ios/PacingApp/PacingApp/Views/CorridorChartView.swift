import SwiftUI
import Charts

/// Moteur d’affichage Swift Charts de la grammaire Pacing.
///
/// Cette vue ne décide rien de l’apparence du graphique : elle traduit une
/// `ChartSpec` reçue de l’API en primitives Swift Charts. Les couleurs, les
/// opacités, l’ordre des couches, les unités, le sens de l’axe des temps et la
/// légende viennent tous de la recette, la même que celle rendue par
/// Matplotlib dans Flet, NiceGUI et DearPyGUI.
///
/// Seule la *technique* est propre à iOS : là où Matplotlib inverse l’axe Y,
/// Swift Charts trace `-temps`, un domaine inversé `[max, min]` produisant des
/// rubans triangulaires au lieu d’aires continues.
struct CorridorChartView: View {
    let spec: ChartSpec?
    var fallbackTitle: String = "Couloir de performance"

    var body: some View {
        if let spec {
            chart(spec)
        } else {
            unavailable
        }
    }

    // MARK: - Rendu de la recette

    private func chart(_ spec: ChartSpec) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(spec.title.isEmpty ? fallbackTitle : spec.title)
                .font(.headline)

            Chart {
                ForEach(Array(spec.layers.enumerated()), id: \.offset) { index, layer in
                    content(spec, layer, index)
                }
            }
            .chartXScale(domain: xDomain(spec))
            .chartYScale(domain: yDomain(spec))
            .chartXAxis { xAxis(spec) }
            .chartYAxis { yAxis(spec) }
            .chartXAxisLabel(spec.x.label)
            .chartYAxisLabel(spec.y.label)
            .chartLegend(.hidden)
            .frame(minHeight: 280)
            .padding(12)
            .background(spec.theme.canvas)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            legend(spec)
        }
    }

    @ChartContentBuilder
    private func content(_ spec: ChartSpec, _ layer: ChartLayer, _ index: Int) -> some ChartContent {
        let rows = spec.rows(layer.source)
        let series = "\(layer.source)-\(index)"

        switch layer.geom {
        case "area":
            ForEach(rows.indices, id: \.self) { position in
                if let x = rows[position].x,
                   let low = layer.ymin.flatMap({ rows[position].value($0) }),
                   let high = layer.ymax.flatMap({ rows[position].value($0) }) {
                    AreaMark(
                        x: .value(spec.x.label, x),
                        yStart: .value("Bas", plotY(spec, low)),
                        yEnd: .value("Haut", plotY(spec, high)),
                        series: .value("Couche", series)
                    )
                    .foregroundStyle(layer.swiftColor)
                    .interpolationMethod(.linear)
                }
            }

        case "line":
            ForEach(rows.indices, id: \.self) { position in
                if let x = rows[position].x,
                   let value = layer.y.flatMap({ rows[position].value($0) }) {
                    LineMark(
                        x: .value(spec.x.label, x),
                        y: .value(spec.y.label, plotY(spec, value)),
                        series: .value("Couche", series)
                    )
                    .foregroundStyle(layer.swiftColor)
                    .lineStyle(stroke(layer))
                    .interpolationMethod(.linear)

                    if layer.marker != nil {
                        PointMark(
                            x: .value(spec.x.label, x),
                            y: .value(spec.y.label, plotY(spec, value))
                        )
                        .foregroundStyle(layer.swiftColor)
                        .symbol(symbol(layer.marker))
                        .symbolSize(pointArea(layer.markerSize ?? 6))
                    }
                }
            }

        default:
            ForEach(rows.indices, id: \.self) { position in
                if let x = rows[position].x,
                   let value = layer.y.flatMap({ rows[position].value($0) }) {
                    PointMark(
                        x: .value(spec.x.label, x),
                        y: .value(spec.y.label, plotY(spec, value))
                    )
                    .foregroundStyle(layer.swiftColor)
                    .symbol(symbol(layer.marker))
                    .symbolSize(layer.size ?? 40)
                }
            }
        }
    }

    // MARK: - Traduction des réglages de la recette

    /// Applique le sens d’axe déclaré par la recette.
    private func plotY(_ spec: ChartSpec, _ value: Double) -> Double {
        spec.y.reverse ? -value : value
    }

    private func stroke(_ layer: ChartLayer) -> StrokeStyle {
        StrokeStyle(
            lineWidth: layer.width ?? 2,
            lineCap: .round,
            dash: layer.dash.map { CGFloat($0) }
        )
    }

    private func symbol(_ marker: String?) -> BasicChartSymbolShape {
        switch marker {
        case "square": return .square
        case "tick": return .plus
        default: return .circle
        }
    }

    /// Swift Charts dimensionne les symboles en aire, Matplotlib en diamètre.
    private func pointArea(_ diameter: Double) -> Double {
        max(diameter * diameter * 0.6, 20)
    }

    private func xDomain(_ spec: ChartSpec) -> ClosedRange<Double> {
        closedRange(spec.xValues, fallback: 0...1)
    }

    private func yDomain(_ spec: ChartSpec) -> ClosedRange<Double> {
        let range = closedRange(spec.yValues, fallback: 0...1)
        guard spec.y.reverse else { return range }
        return plotY(spec, range.upperBound)...plotY(spec, range.lowerBound)
    }

    private func closedRange(_ values: [Double], fallback: ClosedRange<Double>) -> ClosedRange<Double> {
        guard let low = values.min(), let high = values.max() else { return fallback }
        if low == high {
            let pad = max(abs(low) * 0.05, 0.5)
            return (low - pad)...(high + pad)
        }
        return low...high
    }

    @AxisContentBuilder
    private func yAxis(_ spec: ChartSpec) -> some AxisContent {
        AxisMarks(position: .leading) { value in
            AxisGridLine().foregroundStyle(spec.theme.grid)
            AxisValueLabel {
                if let plotted = value.as(Double.self) {
                    Text(spec.y.format(spec.y.reverse ? -plotted : plotted))
                        .font(.caption2)
                }
            }
        }
    }

    @AxisContentBuilder
    private func xAxis(_ spec: ChartSpec) -> some AxisContent {
        if spec.x.isCategorical {
            AxisMarks(values: Array(0..<spec.x.categories.count).map(Double.init)) { value in
                AxisGridLine().foregroundStyle(spec.theme.grid)
                AxisValueLabel {
                    if let plotted = value.as(Double.self) {
                        Text(spec.x.format(plotted))
                            .font(.caption2)
                    }
                }
            }
        } else {
            AxisMarks { value in
                AxisGridLine().foregroundStyle(spec.theme.grid)
                AxisValueLabel {
                    if let plotted = value.as(Double.self) {
                        Text(spec.x.format(plotted))
                            .font(.caption2)
                    }
                }
            }
        }
    }

    // MARK: - Légende déclarée par la recette

    private func legend(_ spec: ChartSpec) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 16) {
                ForEach(spec.legend) { entry in
                    legendItem(entry)
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                ForEach(spec.legend) { entry in
                    legendItem(entry)
                }
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func legendItem(_ entry: ChartLegendEntry) -> some View {
        HStack(spacing: 4) {
            if entry.isLine {
                Capsule()
                    .fill(entry.swiftColor)
                    .frame(width: 14, height: 3)
            } else {
                RoundedRectangle(cornerRadius: 2)
                    .fill(entry.swiftColor)
                    .frame(width: 12, height: 12)
            }
            Text(entry.label)
        }
    }

    private var unavailable: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(fallbackTitle)
                .font(.headline)
            Text("Recette de graphique absente de la réponse : l’API n’a pas renvoyé de champ « spec ».")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, minHeight: 120, alignment: .topLeading)
        .padding(12)
        .background(PacingTheme.canvas)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
