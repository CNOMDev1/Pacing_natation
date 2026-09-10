import SwiftUI

/// Référentiel d'épreuves servi par `GET /api/v1/referentiels/epreuves`.
///
/// Avant cet écran, l'épreuve était figée dans `EventSelection` : l'iPad ne
/// pouvait pas savoir quelles nages, distances et bassins existent réellement
/// dans la base du pays choisi. Sélectionner une épreuve ici alimente les
/// écrans Couloir et Comparaison.
struct EventsReferentialView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                countryPicker

                if let events = store.events {
                    if !events.strokes.isEmpty {
                        strokeTree(events.strokes)
                    }
                    if !events.events.isEmpty {
                        flatEvents(events.events)
                    }
                    if events.isEmpty {
                        Text("Aucune épreuve pour ce pays.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else if store.isLoading {
                    ProgressView("Chargement du référentiel…")
                }

                if let error = store.lastError {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
            .padding(24)
            .frame(maxWidth: 1000, alignment: .leading)
        }
        .background(PacingTheme.canvas.ignoresSafeArea())
        .navigationTitle("Épreuves")
        .task {
            if store.events == nil {
                await store.loadEvents()
            }
        }
    }

    private var countryPicker: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Pays", selection: $store.selection.country) {
                ForEach(CountryCode.allCases) { country in
                    Text(country.label).tag(country)
                }
            }
            .pickerStyle(.segmented)

            Text("Épreuve courante : \(store.selection.eventLabel)")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .onChange(of: store.selection.country) { _, _ in
            Task { await store.loadEvents() }
        }
    }

    /// France et Maroc : arbre nage → distance → bassins.
    private func strokeTree(_ strokes: [StrokeTreeItem]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Nages, distances et bassins disponibles")
                .font(.headline)

            ForEach(strokes) { stroke in
                VStack(alignment: .leading, spacing: 6) {
                    Text(stroke.label)
                        .font(.subheadline.weight(.semibold))

                    ForEach(stroke.distances) { distance in
                        HStack(spacing: 8) {
                            Text("\(distance.distance) \(distance.unit ?? "m")")
                                .font(.caption.monospacedDigit())
                                .frame(width: 72, alignment: .leading)

                            ForEach(distance.pools) { pool in
                                poolButton(stroke: stroke, distance: distance.distance, pool: pool)
                            }
                            Spacer(minLength: 0)
                        }
                    }
                }
                .padding(12)
                .background(.background)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }

    private func poolButton(stroke: StrokeTreeItem, distance: Int, pool: PoolItem) -> some View {
        let strokeCode = stroke.strokeCode
        let poolCode = pool.poolCode
        let isSelected = strokeCode == store.selection.stroke
            && distance == store.selection.distance
            && poolCode == store.selection.pool

        return Button {
            guard let strokeCode, let poolCode else { return }
            store.applyEvent(stroke: strokeCode, distance: distance, pool: poolCode)
        } label: {
            Text(pool.label)
                .font(.caption)
        }
        .buttonStyle(.bordered)
        .tint(isSelected ? PacingTheme.swimmerA : nil)
        .disabled(strokeCode == nil || poolCode == nil)
    }

    /// États-Unis : l'API sert une liste plate d'épreuves, sans arbre.
    private func flatEvents(_ events: [String]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Épreuves (\(events.count))")
                .font(.headline)
            Text("USA Swimming expose une liste plate ; le couloir américain repose sur des catégories d'âge.")
                .font(.caption2)
                .foregroundStyle(.secondary)

            ForEach(events, id: \.self) { event in
                Text(event)
                    .font(.caption.monospacedDigit())
            }
        }
        .padding(12)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
