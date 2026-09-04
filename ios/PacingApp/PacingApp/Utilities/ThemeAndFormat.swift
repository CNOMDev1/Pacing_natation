import SwiftUI

enum PacingTheme {
    static let accent = Color(red: 0.05, green: 0.35, blue: 0.55)

    /// Charte Flet / matplotlib (`corridor_data.py`).
    static let belowMedianOuter = Color(hex: "bfdbfe", opacity: 0.40)
    static let belowMedianInner = Color(hex: "3b82f6", opacity: 0.55)
    static let aboveMedianOuter = Color(hex: "fde68a", opacity: 0.40)
    static let aboveMedianInner = Color(hex: "f59e0b", opacity: 0.55)
    static let median = Color(hex: "666666")
    static let swimmerA = Color(hex: "dc2626")
    static let swimmerB = Color(hex: "059669")
    static let canvas = Color(hex: "f8fafc")
}

private extension Color {
    init(hex: String, opacity: Double = 1) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)
        self.init(
            .sRGB,
            red: Double((value >> 16) & 0xFF) / 255,
            green: Double((value >> 8) & 0xFF) / 255,
            blue: Double(value & 0xFF) / 255,
            opacity: opacity
        )
    }
}

enum TimeFormat {
    /// Affiche un temps brut en secondes (deux décimales).
    static func seconds(_ value: Double?) -> String {
        guard let value, value.isFinite, value >= 0 else { return "—" }
        return String(format: "%.2f", value)
    }

    /// Convertit des secondes en `m:ss.cc` (affichage coach).
    static func mmss(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0 else { return "—" }
        let totalCentis = Int((seconds * 100).rounded())
        let minutes = totalCentis / 6000
        let rem = totalCentis % 6000
        let secs = rem / 100
        let centis = rem % 100
        if minutes > 0 {
            return String(format: "%d:%02d.%02d", minutes, secs, centis)
        }
        return String(format: "%d.%02d", secs, centis)
    }
}
