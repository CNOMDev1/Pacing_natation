import SwiftUI

/// Miroir Swift de la grammaire de graphiques Pacing (`pacing/grammar/spec.py`).
///
/// Ces types ne prennent **aucune** décision d’apparence : ils décodent la
/// recette produite côté Python et transmise par l’API dans le champ `spec`.
/// Couleurs, opacités, géométries, unités et sens d’axe viennent tous de là,
/// ce qui garantit que l’iPad trace le même graphique que Matplotlib au lieu
/// de le redéfinir.
struct ChartSpec: Codable, Sendable {
    let kind: String
    let title: String
    let stat: String?
    let mapping: [String: String]
    let x: ChartScale
    let y: ChartScale
    let theme: ChartTheme
    let layers: [ChartLayer]
    let legend: [ChartLegendEntry]
    let data: [String: [ChartRow]]

    /// Table de données d’une couche, vide si absente.
    func rows(_ source: String) -> [ChartRow] {
        data[source] ?? []
    }

    /// Toutes les valeurs numériques portées par l’axe Y, tous calques confondus.
    var yValues: [Double] {
        layers.flatMap { layer -> [Double] in
            let rows = rows(layer.source)
            return layer.yFields.flatMap { field in
                rows.compactMap { $0.value(field) }
            }
        }
    }

    /// Toutes les abscisses présentes dans les données.
    var xValues: [Double] {
        layers.flatMap { rows($0.source).compactMap(\.x) }
    }
}

/// Échelle d’un canal visuel : libellé, unité, sens et format des étiquettes.
struct ChartScale: Codable, Sendable {
    let label: String
    let unit: String?
    let kind: String
    let reverse: Bool
    let categories: [String]
    let tickFormat: String?

    var isCategorical: Bool { kind == "categorical" }

    enum CodingKeys: String, CodingKey {
        case label, unit, kind, reverse, categories
        case tickFormat = "tick_format"
    }

    /// Formate une valeur d’axe selon le format déclaré par la recette.
    func format(_ value: Double) -> String {
        switch tickFormat {
        case "mm:ss.cc": return TimeFormat.mmss(value)
        case "seconds": return TimeFormat.seconds(value)
        case "integer": return String(Int(value.rounded()))
        default:
            if isCategorical {
                let index = Int(value.rounded())
                return categories.indices.contains(index) ? categories[index] : ""
            }
            return TimeFormat.seconds(value)
        }
    }
}

/// Charte visuelle commune, dérivée de `corridor_data.py`.
struct ChartTheme: Codable, Sendable {
    let figureFacecolor: String
    let axesFacecolor: String
    let gridColor: String
    let gridAlpha: Double
    let gridLinewidth: Double
    let annotationColor: String
    let markerEdgeColor: String

    enum CodingKeys: String, CodingKey {
        case figureFacecolor = "figure_facecolor"
        case axesFacecolor = "axes_facecolor"
        case gridColor = "grid_color"
        case gridAlpha = "grid_alpha"
        case gridLinewidth = "grid_linewidth"
        case annotationColor = "annotation_color"
        case markerEdgeColor = "marker_edge_color"
    }

    var canvas: Color { Color(hex: axesFacecolor) }
    var grid: Color { Color(hex: gridColor, opacity: gridAlpha) }
}

/// Une géométrie de la recette : aire, ligne ou points.
struct ChartLayer: Codable, Sendable {
    let geom: String
    let source: String
    let ymin: String?
    let ymax: String?
    let y: String?
    let fill: String?
    let color: String?
    let alpha: Double
    let width: Double?
    let dash: [Double]
    let marker: String?
    let markerSize: Double?
    let size: Double?
    let label: String?
    let zorder: Int

    enum CodingKeys: String, CodingKey {
        case geom, source, ymin, ymax, y, fill, color, alpha, width, dash
        case marker, size, label, zorder
        case markerSize = "marker_size"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        geom = try container.decode(String.self, forKey: .geom)
        source = try container.decode(String.self, forKey: .source)
        ymin = try container.decodeIfPresent(String.self, forKey: .ymin)
        ymax = try container.decodeIfPresent(String.self, forKey: .ymax)
        y = try container.decodeIfPresent(String.self, forKey: .y)
        fill = try container.decodeIfPresent(String.self, forKey: .fill)
        color = try container.decodeIfPresent(String.self, forKey: .color)
        alpha = try container.decodeIfPresent(Double.self, forKey: .alpha) ?? 1
        width = try container.decodeIfPresent(Double.self, forKey: .width)
        dash = try container.decodeIfPresent([Double].self, forKey: .dash) ?? []
        marker = try container.decodeIfPresent(String.self, forKey: .marker)
        markerSize = try container.decodeIfPresent(Double.self, forKey: .markerSize)
        size = try container.decodeIfPresent(Double.self, forKey: .size)
        label = try container.decodeIfPresent(String.self, forKey: .label)
        zorder = try container.decodeIfPresent(Int.self, forKey: .zorder) ?? 1
    }

    /// Champs de la table portés par l’axe Y, pour le calcul du domaine.
    var yFields: [String] {
        [ymin, ymax, y].compactMap { $0 }
    }

    /// Couleur du trait ou du remplissage, opacité de la recette appliquée.
    var swiftColor: Color {
        Color(hex: fill ?? color ?? "000000", opacity: alpha)
    }
}

/// Entrée de légende déclarée par la recette : même ordre et mêmes libellés
/// que la légende Matplotlib.
struct ChartLegendEntry: Codable, Sendable, Identifiable {
    let label: String
    let color: String
    let kind: String
    let dash: [Double]

    var id: String { "\(kind)-\(label)" }
    var swiftColor: Color { Color(hex: color) }
    var isLine: Bool { kind == "line" }
}

/// Une ligne de données. Les clés numériques alimentent les géométries, les
/// clés textuelles (`x_label`) servent aux étiquettes d’axe.
struct ChartRow: Codable, Sendable {
    let values: [String: Double]
    let labels: [String: String]

    var x: Double? { values["x"] }

    func value(_ field: String) -> Double? { values[field] }

    private struct DynamicKey: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicKey.self)
        var values: [String: Double] = [:]
        var labels: [String: String] = [:]
        for key in container.allKeys {
            if let number = try? container.decode(Double.self, forKey: key) {
                values[key.stringValue] = number
            } else if let text = try? container.decode(String.self, forKey: key) {
                labels[key.stringValue] = text
            }
            // Une valeur nulle signifie « percentile absent à cette abscisse » :
            // la clé reste hors de la table, et la géométrie l’ignore.
        }
        self.values = values
        self.labels = labels
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: DynamicKey.self)
        for (key, value) in values {
            guard let coding = DynamicKey(stringValue: key) else { continue }
            try container.encode(value, forKey: coding)
        }
        for (key, value) in labels {
            guard let coding = DynamicKey(stringValue: key) else { continue }
            try container.encode(value, forKey: coding)
        }
    }
}
