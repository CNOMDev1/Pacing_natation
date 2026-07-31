import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var draftURL: String = ""

    var body: some View {
        Form {
            Section("Source de données") {
                Picker("Mode", selection: $store.dataMode) {
                    ForEach(DataMode.allCases) { mode in
                        Text(mode.label).tag(mode)
                    }
                }
                .onChange(of: store.dataMode) { _, _ in
                    Task { await store.refreshConnection() }
                }

                Text(store.dataMode == .demo
                     ? "Illustre l’UI sans serveur (équivalent fichiers exportés)."
                     : "Consomme FastAPI — même contrat que NiceGUI.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("API FastAPI") {
                TextField("URL de base", text: $draftURL)
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .autocorrectionDisabled()
                    #if os(macOS)
                    .textFieldStyle(.roundedBorder)
                    #endif

                Button("Enregistrer l’URL") {
                    store.apiBaseURL = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
                    Task { await store.refreshConnection() }
                }

                Button("Tester la connexion") {
                    Task { await store.refreshConnection() }
                }

                LabeledContent("État") {
                    Text(store.connectionLabel)
                        .foregroundStyle(store.dataMode == .live && store.isAPIReachable ? .green : .secondary)
                }
            }

            Section("Contrat") {
                Text("Endpoints : /api/v1/pays, /nageur/recherche, /couloir, /comparaison")
                    .font(.caption)
                Text("Temps en secondes côté API ; affichage mm:ss.cc côté client.")
                    .font(.caption)
                Text("Doc : docs/ios_mac_exploration_5_5.md et docs/api_contract.md")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Limites") {
                Text("Pas d’exécution Python sur iPad. Graphiques avancés (heatmap, Grammar of Graphics) hors prototype. Auth absente.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Réglages")
        .onAppear {
            draftURL = store.apiBaseURL
        }
    }
}
