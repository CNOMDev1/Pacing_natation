import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                missionCard
                screensCard
                connectionCard
            }
            .padding(24)
            .frame(maxWidth: 900, alignment: .leading)
        }
        .background(PacingTheme.canvas.ignoresSafeArea())
        .navigationTitle("Accueil")
        .task {
            await store.refreshConnection()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Pacing")
                .font(.system(size: 42, weight: .bold, design: .rounded))
                .foregroundStyle(PacingTheme.accent)
            Text("Prototype terrain iPad / macOS — écosystème XLab")
                .font(.title3)
                .foregroundStyle(.secondary)
        }
    }

    private var missionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Usages coach")
                .font(.headline)
            Text("Consultation au bord du bassin : recherche nageur, couloir d’âge, comparaison. Le calcul reste côté Python (API) ; l’app affiche le JSON.")
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var screensCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Écrans du prototype")
                .font(.headline)
            ForEach([
                ("magnifyingglass", "Recherche", "Autocomplete nageur (name + année)"),
                ("chart.xyaxis.line", "Couloir", "Bandes percentiles + courbe cible"),
                ("person.2", "Comparaison", "Deux nageurs sur le même peloton"),
                ("gearshape", "Réglages", "Mode Démo / Live + URL API"),
            ], id: \.1) { icon, title, subtitle in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: icon)
                        .foregroundStyle(PacingTheme.accent)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title).font(.subheadline.weight(.semibold))
                        Text(subtitle).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var connectionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Connexion moteur Python")
                .font(.headline)
            Label(store.connectionLabel, systemImage: store.dataMode == .demo ? "shippingbox" : "network")
            Text(store.dataMode == .demo
                 ? "Données JSON embarquées (secours hors ligne / démo)."
                 : "Client HTTP → \(store.apiBaseURL)/api/v1")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let error = store.lastError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
