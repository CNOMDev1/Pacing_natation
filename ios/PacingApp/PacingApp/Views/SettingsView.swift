import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var draftURL: String = ""
    @State private var draftProjectPath: String = ""

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

                #if os(macOS)
                TextField("Chemin projet Pacing", text: $draftProjectPath)
                    .textFieldStyle(.roundedBorder)
                    .help("Dossier contenant .venv/ (ex. ~/Desktop/Pacing)")

                Button("Enregistrer") {
                    store.apiBaseURL = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
                    store.projectPath = draftProjectPath.trimmingCharacters(in: .whitespacesAndNewlines)
                }
                #else
                Button("Enregistrer l’URL") {
                    store.apiBaseURL = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
                }
                #endif

                Button {
                    store.apiBaseURL = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
                    #if os(macOS)
                    store.projectPath = draftProjectPath.trimmingCharacters(in: .whitespacesAndNewlines)
                    #endif
                    Task { await store.testConnection() }
                } label: {
                    if store.isTestingConnection {
                        Label("Test en cours…", systemImage: "hourglass")
                    } else {
                        Label("Tester la connexion", systemImage: "bolt.horizontal.circle")
                    }
                }
                .disabled(store.isTestingConnection)

                LabeledContent("État") {
                    Text(store.connectionLabel)
                        .foregroundStyle(store.dataMode == .live && store.isAPIReachable ? .green : .secondary)
                }

                if let message = store.connectionStatusMessage {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                #if os(macOS)
                Text("Sur Mac, ce bouton lance si besoin : uvicorn \(LocalAPIServerLauncher.uvicornTarget) --reload")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                #endif
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
            draftProjectPath = store.projectPath
        }
    }
}
