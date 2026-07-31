import SwiftUI

struct SwimmerSearchView: View {
    @EnvironmentObject private var store: AppStore
    @State private var query: String = ""
    @State private var hasSearched = false
    @FocusState private var isQueryFocused: Bool

    var body: some View {
        List {
            if store.dataMode == .demo {
                Section {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Mode Démo actif")
                            .font(.headline)
                        Text("Tu ne vois que quelques nageurs fictifs (ex. ALAMI Sara). Les vraies données Maroc/France passent par l’API Live.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Button {
                            Task {
                                await store.enableLiveMode()
                                if !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                    await store.searchSwimmers(query: query)
                                    hasSearched = true
                                }
                            }
                        } label: {
                            Label(
                                store.apiAvailable ? "Utiliser l’API Live" : "Passer en Live (lancer uvicorn)",
                                systemImage: "network"
                            )
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .padding(.vertical, 4)
                }
            }

            Section {
                EventFilterBar(selection: $store.selection)
            }

            Section("Recherche") {
                TextField("Nom du nageur…", text: $query)
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .autocorrectionDisabled()
                    .focused($isQueryFocused)
                    .submitLabel(.search)
                    .onSubmit {
                        runSearch()
                    }

                Button {
                    runSearch()
                } label: {
                    Label(
                        store.isLoading ? "Recherche…" : "Rechercher",
                        systemImage: "magnifyingglass"
                    )
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(store.isLoading || query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                if store.isLoading {
                    ProgressView("Recherche…")
                }

                if hasSearched && !store.isLoading && store.searchResults.isEmpty {
                    Text(emptyMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                ForEach(store.searchResults) { swimmer in
                    Button {
                        store.selectedSwimmer = swimmer
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(swimmer.label)
                                Text("\(swimmer.country.label) · \(swimmer.gender ?? "—")")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if store.selectedSwimmer?.id == swimmer.id {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(PacingTheme.accent)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                }
            }

            if let selected = store.selectedSwimmer {
                Section("Sélection") {
                    Text("\(selected.name) sera utilisé dans Couloir / Comparaison.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let error = store.lastError {
                Section {
                    Text(error).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Recherche")
        .task {
            await store.refreshConnection()
        }
    }

    private var emptyMessage: String {
        if store.dataMode == .demo {
            return "Aucun résultat en Démo. Essaie « ALAMI », ou passe en Live pour chercher Salma dans les données Maroc."
        }
        if store.dataMode == .live && !store.isAPIReachable {
            return "API hors ligne. Lance : uvicorn pacing.api.main:app --reload — puis Réglages → Tester la connexion."
        }
        return "Aucun résultat pour ces filtres. Élargis le genre (Tous) ou change nage/distance/bassin."
    }

    private func runSearch() {
        isQueryFocused = false
        hasSearched = true
        Task {
            await store.searchSwimmers(query: query)
        }
    }
}

struct EventFilterBar: View {
    @Binding var selection: EventSelection

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Pays", selection: $selection.country) {
                ForEach(CountryCode.allCases) { code in
                    Text(code.label).tag(code)
                }
            }
            Picker("Nage", selection: $selection.stroke) {
                ForEach(StrokeCode.allCases) { code in
                    Text(code.label).tag(code)
                }
            }
            Picker("Distance", selection: $selection.distance) {
                ForEach(EventSelection.distances, id: \.self) { d in
                    Text("\(d) m").tag(d)
                }
            }
            Picker("Bassin", selection: $selection.pool) {
                ForEach(PoolCode.allCases) { code in
                    Text(code.label).tag(code)
                }
            }
            Picker("Genre", selection: $selection.gender) {
                ForEach(GenderFilter.allCases) { g in
                    Text(g.label).tag(g)
                }
            }
        }
    }
}
