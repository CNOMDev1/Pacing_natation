import SwiftUI

struct CorridorView: View {
    @EnvironmentObject private var store: AppStore
    @State private var includeSwimmer = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                EventFilterBar(selection: $store.selection)
                    .padding(16)
                    .background(.background)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

                Toggle("Superposer le nageur sélectionné", isOn: $includeSwimmer)
                if let swimmer = store.selectedSwimmer {
                    Text("Cible : \(swimmer.label)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else if includeSwimmer {
                    Text("Aucun nageur sélectionné — le couloir global sera affiché (ou démo Alice).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Button {
                    Task { await store.loadCorridor(includeSelectedSwimmer: includeSwimmer && store.selectedSwimmer != nil) }
                } label: {
                    Label(store.isLoading ? "Chargement…" : "Charger le couloir", systemImage: "arrow.triangle.2.circlepath")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(store.isLoading)

                if let corridor = store.corridor {
                    metaBlock(corridor)
                    CorridorChartView(
                        bands: corridor.bands,
                        swimmerA: corridor.swimmer,
                        title: corridor.meta.event
                    )
                    bandTable(corridor.bands)
                }

                if let error = store.lastError {
                    Text(error).foregroundStyle(.red).font(.caption)
                }
            }
            .padding(24)
            .frame(maxWidth: 1000, alignment: .leading)
        }
        .background(PacingTheme.canvas.ignoresSafeArea())
        .navigationTitle("Couloir")
        .task {
            if store.corridor == nil {
                await store.loadCorridor(includeSelectedSwimmer: false)
            }
        }
    }

    private func metaBlock(_ corridor: CorridorResponse) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(corridor.meta.event)
                .font(.title2.weight(.semibold))
            Text("\(corridor.meta.country.label) · \(corridor.meta.corridorType) · n=\(corridor.meta.rowCount) · statut \(corridor.status.rawValue)")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func bandTable(_ bands: [CorridorBand]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Bandes (secondes)")
                .font(.headline)
            ForEach(bands) { band in
                HStack {
                    Text(band.xLabel).frame(width: 36, alignment: .leading)
                    Text(TimeFormat.mmss(band.p10 ?? 0)).frame(maxWidth: .infinity)
                    Text(TimeFormat.mmss(band.p50 ?? 0)).frame(maxWidth: .infinity)
                    Text(TimeFormat.mmss(band.p90 ?? 0)).frame(maxWidth: .infinity)
                    Text("n=\(band.n)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .frame(width: 48, alignment: .trailing)
                }
                .font(.caption.monospacedDigit())
            }
        }
        .padding(12)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
