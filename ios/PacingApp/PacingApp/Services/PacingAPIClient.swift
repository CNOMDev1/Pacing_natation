import Foundation

enum PacingAPIError: LocalizedError {
    case unreachable(String)
    case http(Int, String)
    case decoding(String)
    case invalidURL

    var errorDescription: String? {
        switch self {
        case .unreachable(let base):
            return "API injoignable (\(base)). Lancez uvicorn ou passez en mode Démo."
        case .http(let code, let detail):
            return "HTTP \(code) — \(detail)"
        case .decoding(let detail):
            return "Décodage JSON : \(detail)"
        case .invalidURL:
            return "URL API invalide."
        }
    }
}

/// Client HTTP minimal pour le prototype FastAPI `/api/v1`.
struct PacingAPIClient: Sendable {
    var baseURL: String
    var timeout: TimeInterval = 30

    func listCountries() async throws -> CountriesResponse {
        try await get("/api/v1/pays")
    }

    func searchSwimmers(
        query: String,
        country: CountryCode,
        gender: GenderFilter = .all,
        stroke: StrokeCode? = nil,
        distance: Int? = nil,
        pool: PoolCode? = nil,
        limit: Int = 30
    ) async throws -> SwimmerSearchResponse {
        var params: [String: String] = [
            "q": query,
            "country": country.rawValue,
            "gender": gender.rawValue,
            "limit": String(limit),
        ]
        if let stroke { params["stroke"] = stroke.rawValue }
        if let distance { params["distance"] = String(distance) }
        if let pool { params["pool"] = pool.rawValue }
        return try await get("/api/v1/nageur/recherche", query: params)
    }

    func fetchCorridor(
        selection: EventSelection,
        corridorType: CorridorType,
        swimmerName: String? = nil,
        swimmerYob: Int? = nil,
        swimmerCountry: CountryCode? = nil
    ) async throws -> CorridorResponse {
        var query: [String: String] = [
            "country": selection.country.rawValue,
            "stroke": selection.stroke.rawValue,
            "distance": String(selection.distance),
            "pool": selection.pool.rawValue,
            "gender": selection.gender.rawValue,
            "corridor_type": corridorType.rawValue,
        ]
        if let swimmerName, !swimmerName.isEmpty {
            query["swimmer_name"] = swimmerName
        }
        if let swimmerYob {
            query["swimmer_yob"] = String(swimmerYob)
        }
        if let swimmerCountry {
            query["swimmer_country"] = swimmerCountry.rawValue
        }
        return try await get("/api/v1/couloir", query: query)
    }

    func fetchCompare(
        selection: EventSelection,
        swimmerAName: String,
        swimmerAYob: Int?,
        swimmerACountry: CountryCode?,
        swimmerBName: String,
        swimmerBYob: Int?,
        swimmerBCountry: CountryCode?
    ) async throws -> CompareResponse {
        var query: [String: String] = [
            "country": selection.country.rawValue,
            "stroke": selection.stroke.rawValue,
            "distance": String(selection.distance),
            "pool": selection.pool.rawValue,
            "gender": selection.gender.rawValue,
            "swimmer_a_name": swimmerAName,
            "swimmer_b_name": swimmerBName,
        ]
        if let swimmerAYob { query["swimmer_a_yob"] = String(swimmerAYob) }
        if let swimmerBYob { query["swimmer_b_yob"] = String(swimmerBYob) }
        if let swimmerACountry { query["swimmer_a_country"] = swimmerACountry.rawValue }
        if let swimmerBCountry { query["swimmer_b_country"] = swimmerBCountry.rawValue }
        return try await get("/api/v1/comparaison", query: query)
    }

    func ping() async -> Bool {
        do {
            _ = try await listCountries()
            return true
        } catch {
            return false
        }
    }

    private func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        let base = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard var comps = URLComponents(string: base + path) else {
            throw PacingAPIError.invalidURL
        }
        if !query.isEmpty {
            comps.queryItems = query
                .map { URLQueryItem(name: $0.key, value: $0.value) }
                .sorted { $0.name < $1.name }
        }
        guard let url = comps.url else { throw PacingAPIError.invalidURL }

        var request = URLRequest(url: url)
        request.timeoutInterval = timeout
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw PacingAPIError.unreachable(baseURL)
        }

        guard let http = response as? HTTPURLResponse else {
            throw PacingAPIError.unreachable(baseURL)
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? "erreur"
            throw PacingAPIError.http(http.statusCode, detail)
        }

        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw PacingAPIError.decoding(error.localizedDescription)
        }
    }
}
