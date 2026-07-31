import Foundation
import Combine

@MainActor
final class AppStore: ObservableObject {
    @Published var dataMode: DataMode {
        didSet { UserDefaults.standard.set(dataMode.rawValue, forKey: Keys.mode) }
    }

    @Published var apiBaseURL: String {
        didSet { UserDefaults.standard.set(apiBaseURL, forKey: Keys.apiURL) }
    }

    @Published var selection: EventSelection
    @Published var isAPIReachable: Bool = false
    @Published var lastError: String?
    @Published var selectedSwimmer: SwimmerSearchResult?
    @Published var corridor: CorridorResponse?
    @Published var compare: CompareResponse?
    @Published var searchResults: [SwimmerSearchResult] = []
    @Published var isLoading: Bool = false
    /// True si l'API répond, même si l'utilisateur est encore en mode Démo.
    @Published var apiAvailable: Bool = false

    private enum Keys {
        static let mode = "pacing.dataMode"
        static let apiURL = "pacing.apiBaseURL"
    }

    init() {
        let savedMode = UserDefaults.standard.string(forKey: Keys.mode).flatMap(DataMode.init(rawValue:))
        // Par défaut Live dès qu'on cible les vraies données terrain.
        dataMode = savedMode ?? .live
        apiBaseURL = UserDefaults.standard.string(forKey: Keys.apiURL) ?? "http://127.0.0.1:8000"
        selection = EventSelection()
    }

    var connectionLabel: String {
        switch dataMode {
        case .demo:
            return apiAvailable ? "Mode démo (API dispo)" : "Mode démo"
        case .live:
            return isAPIReachable ? "API connectée" : "API hors ligne"
        }
    }

    private var client: PacingAPIClient {
        PacingAPIClient(baseURL: apiBaseURL)
    }

    func refreshConnection() async {
        let reachable = await client.ping()
        apiAvailable = reachable
        if dataMode == .live {
            isAPIReachable = reachable
        } else {
            isAPIReachable = false
        }
    }

    /// Bascule vers l'API Live et vérifie la connexion.
    func enableLiveMode() async {
        dataMode = .live
        await refreshConnection()
    }

    func searchSwimmers(query: String) async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 1 else {
            searchResults = []
            return
        }
        isLoading = true
        lastError = nil
        defer { isLoading = false }

        do {
            let response: SwimmerSearchResponse
            switch dataMode {
            case .demo:
                response = MockPacingService.search(query: trimmed, country: selection.country)
            case .live:
                response = try await client.searchSwimmers(
                    query: trimmed,
                    country: selection.country,
                    gender: selection.gender,
                    stroke: selection.stroke,
                    distance: selection.distance,
                    pool: selection.pool
                )
                isAPIReachable = true
                apiAvailable = true
            }
            searchResults = response.results
        } catch {
            lastError = error.localizedDescription
            searchResults = []
            isAPIReachable = false
        }
    }

    func loadCorridor(includeSelectedSwimmer: Bool) async {
        isLoading = true
        lastError = nil
        defer { isLoading = false }

        let name = includeSelectedSwimmer ? selectedSwimmer?.name : nil
        let yob = includeSelectedSwimmer ? selectedSwimmer?.yearOfBirth : nil
        let type: CorridorType = name == nil ? .ageGlobal : .ageTarget

        do {
            switch dataMode {
            case .demo:
                corridor = MockPacingService.corridor(
                    selection: selection,
                    swimmerName: name,
                    swimmerYob: yob
                )
            case .live:
                corridor = try await client.fetchCorridor(
                    selection: selection,
                    corridorType: type,
                    swimmerName: name,
                    swimmerYob: yob,
                    swimmerCountry: selectedSwimmer?.country
                )
                isAPIReachable = true
            }
        } catch {
            lastError = error.localizedDescription
            isAPIReachable = false
        }
    }

    func loadCompare(nameA: String, yobA: Int?, nameB: String, yobB: Int?, countryB: CountryCode) async {
        isLoading = true
        lastError = nil
        defer { isLoading = false }

        do {
            switch dataMode {
            case .demo:
                compare = MockPacingService.compare(
                    selection: selection,
                    nameA: nameA,
                    yobA: yobA,
                    nameB: nameB,
                    yobB: yobB,
                    countryB: countryB
                )
            case .live:
                compare = try await client.fetchCompare(
                    selection: selection,
                    swimmerAName: nameA,
                    swimmerAYob: yobA,
                    swimmerACountry: selection.country,
                    swimmerBName: nameB,
                    swimmerBYob: yobB,
                    swimmerBCountry: countryB
                )
                isAPIReachable = true
            }
        } catch {
            lastError = error.localizedDescription
            isAPIReachable = false
        }
    }
}
