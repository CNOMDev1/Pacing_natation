import SwiftUI

/// Racine de navigation : colonne latérale (iPad / Mac) + détail.
struct ContentView: View {
    @EnvironmentObject private var store: AppStore
    @State private var selection: AppDestination? = .home

    var body: some View {
        NavigationSplitView {
            List(AppDestination.allCases, selection: $selection) { destination in
                Label(destination.title, systemImage: destination.systemImage)
                    .tag(destination)
            }
            .navigationTitle("Pacing")
            .safeAreaInset(edge: .bottom) {
                connectionBadge
                    .padding()
            }
        } detail: {
            NavigationStack {
                detailView
            }
        }
    }

    @ViewBuilder
    private var detailView: some View {
        switch selection ?? .home {
        case .home:
            HomeView()
        case .search:
            SwimmerSearchView()
        case .corridor:
            CorridorView()
        case .compare:
            CompareView()
        case .settings:
            SettingsView()
        }
    }

    private var connectionBadge: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(store.dataMode == .demo ? Color.orange : (store.isAPIReachable ? Color.green : Color.red))
                .frame(width: 8, height: 8)
            Text(store.connectionLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
        }
    }
}

enum AppDestination: String, CaseIterable, Hashable, Identifiable {
    case home
    case search
    case corridor
    case compare
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: return "Accueil"
        case .search: return "Recherche"
        case .corridor: return "Couloir"
        case .compare: return "Comparaison"
        case .settings: return "Réglages"
        }
    }

    var systemImage: String {
        switch self {
        case .home: return "house"
        case .search: return "magnifyingglass"
        case .corridor: return "chart.xyaxis.line"
        case .compare: return "person.2"
        case .settings: return "gearshape"
        }
    }
}
