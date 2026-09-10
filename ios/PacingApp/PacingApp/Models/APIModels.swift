import Foundation

// MARK: - Enums API

enum CountryCode: String, Codable, CaseIterable, Identifiable, Sendable {
    case FR, MA, US

    var id: String { rawValue }

    var label: String {
        switch self {
        case .FR: return "France"
        case .MA: return "Maroc"
        case .US: return "États-Unis"
        }
    }
}

enum StrokeCode: String, Codable, CaseIterable, Identifiable, Sendable {
    case FR, BK, BR, FL, IM

    var id: String { rawValue }

    var label: String {
        switch self {
        case .FR: return "Nage libre"
        case .BK: return "Dos"
        case .BR: return "Brasse"
        case .FL: return "Papillon"
        case .IM: return "4 nages"
        }
    }
}

enum PoolCode: String, Codable, CaseIterable, Identifiable, Sendable {
    case LCM, SCM, SCY

    var id: String { rawValue }

    var label: String {
        switch self {
        case .LCM: return "50 m"
        case .SCM: return "25 m"
        case .SCY: return "Yards"
        }
    }
}

enum GenderFilter: String, Codable, CaseIterable, Identifiable, Sendable {
    case F, M
    case all = "all"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .F: return "Féminin"
        case .M: return "Masculin"
        case .all: return "Tous"
        }
    }
}

enum ApiStatus: String, Codable, Sendable {
    case ok
    case empty
    case notFound = "not_found"
}

enum CorridorType: String, Codable, CaseIterable, Identifiable, Sendable {
    case ageGlobal = "age_global"
    case ageTarget = "age_target"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .ageGlobal: return "Couloir global (âge)"
        case .ageTarget: return "Couloir + nageur cible"
        }
    }
}

enum DataMode: String, CaseIterable, Identifiable, Sendable {
    case demo
    case live

    var id: String { rawValue }

    var label: String {
        switch self {
        case .demo: return "Démo (JSON embarqué)"
        case .live: return "Live (API FastAPI)"
        }
    }
}

// MARK: - Payloads

struct CountryItem: Codable, Identifiable, Hashable, Sendable {
    let code: CountryCode
    let label: String
    var id: String { code.rawValue }
}

struct CountriesResponse: Codable, Sendable {
    let countries: [CountryItem]
}

// MARK: - Format d'erreur unique de l'API

/// Un champ fautif d'une erreur de validation (422).
struct ApiErrorDetail: Codable, Sendable {
    let field: String
    let message: String
    let type: String?
}

/// Contenu d'une erreur API.
struct ApiErrorBody: Codable, Sendable {
    let code: String
    let message: String
    let details: [ApiErrorDetail]?
}

/// Enveloppe `{"error": {...}}` commune à toutes les réponses 4xx / 5xx.
///
/// Permet d'afficher le message de l'API au lieu du corps JSON brut.
struct ApiErrorEnvelope: Codable, Sendable {
    let error: ApiErrorBody
}

// MARK: - Référentiel d'épreuves

struct PoolItem: Codable, Identifiable, Hashable, Sendable {
    let code: String
    let label: String

    var id: String { code }
    var poolCode: PoolCode? { PoolCode(rawValue: code) }
}

struct DistanceItem: Codable, Identifiable, Hashable, Sendable {
    let distance: Int
    let unit: String?
    let pools: [PoolItem]

    var id: Int { distance }
}

struct StrokeTreeItem: Codable, Identifiable, Hashable, Sendable {
    let code: String
    let label: String
    let distances: [DistanceItem]

    var id: String { code }
    var strokeCode: StrokeCode? { StrokeCode(rawValue: code) }
}

/// Réponse `GET /referentiels/epreuves`.
///
/// La forme dépend du pays : arbre `strokes` pour FR et MA, liste plate
/// `events` pour les États-Unis.
struct EventsReferentialResponse: Codable, Sendable {
    let country: CountryCode
    let strokes: [StrokeTreeItem]
    let events: [String]

    var isEmpty: Bool { strokes.isEmpty && events.isEmpty }
}

struct SwimmerSearchResult: Codable, Identifiable, Hashable, Sendable {
    let label: String
    let name: String
    let yearOfBirth: Int?
    let gender: String?
    let country: CountryCode

    var id: String { "\(country.rawValue)-\(name)-\(yearOfBirth ?? 0)" }

    enum CodingKeys: String, CodingKey {
        case label, name, gender, country
        case yearOfBirth = "year_of_birth"
    }
}

struct SwimmerSearchResponse: Codable, Sendable {
    let status: ApiStatus
    let query: String
    let count: Int
    let results: [SwimmerSearchResult]
    let message: String?
}

struct CreateSwimmerRequest: Codable, Sendable {
    let name: String
    let yearOfBirth: Int?
    let gender: String?
    let country: CountryCode
    let club: String?
    let stroke: StrokeCode
    let distance: Int
    let pool: PoolCode
    let timeS: Double?
    let timeText: String?
    let meetDate: String?
    let age: Double?

    enum CodingKeys: String, CodingKey {
        case name, gender, country, club, stroke, distance, pool, age
        case yearOfBirth = "year_of_birth"
        case timeS = "time_s"
        case timeText = "time_text"
        case meetDate = "meet_date"
    }
}

struct CreateSwimmerResponse: Codable, Sendable {
    let status: ApiStatus
    let path: String
    let swimmer: SwimmerSearchResult
}

struct CorridorUnits: Codable, Sendable {
    let age: String?
    let ageGroup: String?
    let time: String
    let distance: String?

    enum CodingKeys: String, CodingKey {
        case age, time, distance
        case ageGroup = "age_group"
    }
}

struct CorridorMeta: Codable, Sendable {
    let country: CountryCode
    let corridorType: String
    let event: String
    let stroke: String
    let distance: Int
    let pool: String
    let gender: String
    let swimmerCountry: CountryCode?
    let units: CorridorUnits
    let rowCount: Int

    enum CodingKeys: String, CodingKey {
        case country, event, stroke, distance, pool, gender, units
        case corridorType = "corridor_type"
        case swimmerCountry = "swimmer_country"
        case rowCount = "row_count"
    }
}

struct CorridorBand: Codable, Identifiable, Sendable {
    let age: Int?
    let ageGroup: String?
    let n: Int
    let p10: Double?
    let p25: Double?
    let p50: Double?
    let p75: Double?
    let p90: Double?

    var id: String { ageGroup ?? "\(age ?? -1)" }

    /// Abscisse numérique (âge ou index de catégorie).
    var xValue: Double {
        if let age { return Double(age) }
        return Double(ageGroup?.hashValue ?? 0)
    }

    var xLabel: String {
        if let age { return "\(age)" }
        return ageGroup ?? "?"
    }

    enum CodingKeys: String, CodingKey {
        case age, n, p10, p25, p50, p75, p90
        case ageGroup = "age_group"
    }
}

struct SwimmerPoint: Codable, Identifiable, Sendable {
    let age: Double?
    let ageGroup: String?
    let timeS: Double

    var id: String { "\(age ?? 0)-\(ageGroup ?? "")-\(timeS)" }

    var xValue: Double {
        if let age { return age }
        return Double(ageGroup?.hashValue ?? 0)
    }

    enum CodingKeys: String, CodingKey {
        case age
        case ageGroup = "age_group"
        case timeS = "time_s"
    }
}

struct CorridorSwimmer: Codable, Sendable {
    let name: String
    let yearOfBirth: Int?
    let country: CountryCode?
    let gender: String?
    let points: [SwimmerPoint]

    enum CodingKeys: String, CodingKey {
        case name, country, gender, points
        case yearOfBirth = "year_of_birth"
    }

    var displayName: String {
        if let yearOfBirth {
            return "\(name) (\(yearOfBirth))"
        }
        return name
    }
}

struct CorridorResponse: Codable, Sendable {
    let status: ApiStatus
    let meta: CorridorMeta
    let bands: [CorridorBand]
    let swimmer: CorridorSwimmer?
    /// Recette du graphique (grammaire Pacing) : ce que l’iPad trace.
    let spec: ChartSpec?
    let imageBase64: String?
    let missing: [String]?

    enum CodingKeys: String, CodingKey {
        case status, meta, bands, swimmer, spec, missing
        case imageBase64 = "image_base64"
    }
}

struct CompareResponse: Codable, Sendable {
    let status: ApiStatus
    let meta: CorridorMeta
    let bands: [CorridorBand]
    let swimmerA: CorridorSwimmer?
    let swimmerB: CorridorSwimmer?
    /// Recette du graphique (grammaire Pacing) : ce que l’iPad trace.
    let spec: ChartSpec?
    let imageBase64: String?
    let missing: [String]?

    enum CodingKeys: String, CodingKey {
        case status, meta, bands, spec, missing
        case swimmerA = "swimmer_a"
        case swimmerB = "swimmer_b"
        case imageBase64 = "image_base64"
    }
}

/// Filtres partagés pour le couloir / la comparaison.
struct EventSelection: Equatable, Sendable {
    var country: CountryCode = .FR
    var stroke: StrokeCode = .FR
    var distance: Int = 100
    var pool: PoolCode = .LCM
    var gender: GenderFilter = .F

    var eventLabel: String {
        "\(distance) \(stroke.rawValue) \(pool.rawValue)"
    }

    static let distances = [50, 100, 200, 400, 800, 1500]
}
