import SwiftUI

enum PacingTheme {
    static let accent = Color(red: 0.05, green: 0.35, blue: 0.55)
    static let bandOuter = Color(red: 0.55, green: 0.72, blue: 0.85).opacity(0.35)
    static let bandInner = Color(red: 0.30, green: 0.55, blue: 0.72).opacity(0.45)
    static let median = Color(red: 0.08, green: 0.28, blue: 0.45)
    static let swimmerA = Color(red: 0.85, green: 0.35, blue: 0.12)
    static let swimmerB = Color(red: 0.15, green: 0.55, blue: 0.40)
    static let canvas = Color(red: 0.96, green: 0.97, blue: 0.98)
}

enum TimeFormat {
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
