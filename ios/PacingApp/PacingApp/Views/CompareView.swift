import SwiftUI

struct CompareView: View {
    @EnvironmentObject private var store: AppStore
    @State private var nameA: String = "DUPONT Alice"
    @State private var yobA: String = "2008"
    @State private var nameB: String = "ALAMI Sara"
    @State private var yobB: String = "2009"
    @State private var countryB: CountryCode = .MA

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                EventFilterBar(selection: $store.selection)
                    .padding(16)
                    .background(.background)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 12) {
                    GridRow {
                        Text("Nageur A").font(.headline)
                        Text("Nageur B").font(.headline)
                    }
                    GridRow {
                        TextField("Nom A", text: $nameA)
                            .textFieldStyle(.roundedBorder)
                        TextField("Nom B", text: $nameB)
                            .textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        TextField("Année A", text: $yobA)
                            .textFieldStyle(.roundedBorder)
                        TextField("Année B", text: $yobB)
                            .textFieldStyle(.roundedBorder)
                    }
                    GridRow {
                        Text("Pays A = peloton (\(store.selection.country.label))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Picker("Pays B", selection: $countryB) {
                            ForEach(CountryCode.allCases) { c in
                                Text(c.label).tag(c)
                            }
                        }
                    }
                }

                Button {
                    Task {
                        await store.loadCompare(
                            nameA: nameA,
                            yobA: Int(yobA),
                            nameB: nameB,
                            yobB: Int(yobB),
                            countryB: countryB
                        )
                    }
                } label: {
                    Label(store.isLoading ? "Chargement…" : "Comparer", systemImage: "person.2")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(store.isLoading || nameA.isEmpty || nameB.isEmpty)

                if let compare = store.compare {
                    Text(compare.meta.event)
                        .font(.title2.weight(.semibold))
                    Text("Statut \(compare.status.rawValue)")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    bandTable(compare.bands)
                    if let a = compare.swimmerA {
                        swimmerTable(a)
                    }
                    if let b = compare.swimmerB {
                        swimmerTable(b)
                    }
                }

                if let error = store.lastError {
                    Text(error).foregroundStyle(.red).font(.caption)
                }
            }
            .padding(24)
            .frame(maxWidth: 1000, alignment: .leading)
        }
        .background(PacingTheme.canvas.ignoresSafeArea())
        .navigationTitle("Comparaison")
        .onAppear {
            if let selected = store.selectedSwimmer {
                nameA = selected.name
                if let yob = selected.yearOfBirth {
                    yobA = String(yob)
                }
            }
        }
    }

    private func bandTable(_ bands: [CorridorBand]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Bandes (secondes)")
                .font(.headline)
            Text("P10 / P25 : plus rapides · P50 : médiane · P75 / P90 : plus lents · n : nombre de courses")
                .font(.caption2)
                .foregroundStyle(.secondary)
            HStack {
                Text("Âge").frame(width: 36, alignment: .leading)
                Text("P10").frame(maxWidth: .infinity)
                Text("P25").frame(maxWidth: .infinity)
                Text("P50").frame(maxWidth: .infinity)
                Text("P75").frame(maxWidth: .infinity)
                Text("P90").frame(maxWidth: .infinity)
                Text("n")
                    .frame(width: 48, alignment: .trailing)
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            ForEach(bands) { band in
                HStack {
                    Text(band.xLabel).frame(width: 36, alignment: .leading)
                    Text(TimeFormat.seconds(band.p10)).frame(maxWidth: .infinity)
                    Text(TimeFormat.seconds(band.p25)).frame(maxWidth: .infinity)
                    Text(TimeFormat.seconds(band.p50)).frame(maxWidth: .infinity)
                    Text(TimeFormat.seconds(band.p75)).frame(maxWidth: .infinity)
                    Text(TimeFormat.seconds(band.p90)).frame(maxWidth: .infinity)
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

    private func swimmerTable(_ swimmer: CorridorSwimmer) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(swimmer.displayName)
                .font(.headline)
            ForEach(swimmer.points) { point in
                HStack {
                    Text(point.age.map { String(format: "%.0f", $0) } ?? point.ageGroup ?? "?")
                        .frame(width: 36, alignment: .leading)
                    Text(TimeFormat.mmss(point.timeS))
                    Spacer()
                }
                .font(.caption.monospacedDigit())
            }
        }
        .padding(12)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
