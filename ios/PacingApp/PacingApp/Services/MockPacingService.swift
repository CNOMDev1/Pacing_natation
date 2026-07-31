import Foundation

/// Service hors ligne : payloads conformes au contrat `/api/v1`.
enum MockPacingService {
    static func countries() -> CountriesResponse {
        CountriesResponse(countries: [
            CountryItem(code: .FR, label: "France"),
            CountryItem(code: .MA, label: "Maroc"),
            CountryItem(code: .US, label: "États-Unis"),
        ])
    }

    static func search(query: String, country: CountryCode) -> SwimmerSearchResponse {
        let all = demoSwimmers.filter { $0.country == country }
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let hits = all.filter {
            q.isEmpty || $0.name.lowercased().contains(q) || $0.label.lowercased().contains(q)
        }
        return SwimmerSearchResponse(
            status: hits.isEmpty ? .empty : .ok,
            query: query,
            count: hits.count,
            results: hits,
            message: hits.isEmpty ? "Aucun nageur (données démo)" : nil
        )
    }

    static func corridor(
        selection: EventSelection,
        swimmerName: String?,
        swimmerYob: Int?
    ) -> CorridorResponse {
        if let bundled = loadBundledCorridor(), swimmerName == nil {
            return bundled
        }
        let bands = demoBands
        let swimmer: CorridorSwimmer?
        if let swimmerName, !swimmerName.isEmpty {
            swimmer = CorridorSwimmer(
                name: swimmerName,
                yearOfBirth: swimmerYob ?? 2008,
                country: selection.country,
                gender: selection.gender.rawValue,
                points: demoSwimmerPoints
            )
        } else {
            swimmer = nil
        }
        return CorridorResponse(
            status: .ok,
            meta: CorridorMeta(
                country: selection.country,
                corridorType: swimmer == nil ? CorridorType.ageGlobal.rawValue : CorridorType.ageTarget.rawValue,
                event: selection.eventLabel,
                stroke: selection.stroke.rawValue,
                distance: selection.distance,
                pool: selection.pool.rawValue,
                gender: selection.gender.rawValue,
                swimmerCountry: selection.country,
                units: CorridorUnits(age: "years", ageGroup: nil, time: "seconds", distance: "m"),
                rowCount: 12_450
            ),
            bands: bands,
            swimmer: swimmer,
            imageBase64: nil,
            missing: nil
        )
    }

    static func compare(
        selection: EventSelection,
        nameA: String,
        yobA: Int?,
        nameB: String,
        yobB: Int?,
        countryB: CountryCode
    ) -> CompareResponse {
        CompareResponse(
            status: .ok,
            meta: CorridorMeta(
                country: selection.country,
                corridorType: CorridorType.ageTarget.rawValue,
                event: selection.eventLabel,
                stroke: selection.stroke.rawValue,
                distance: selection.distance,
                pool: selection.pool.rawValue,
                gender: selection.gender.rawValue,
                swimmerCountry: nil,
                units: CorridorUnits(age: "years", ageGroup: nil, time: "seconds", distance: "m"),
                rowCount: 12_450
            ),
            bands: demoBands,
            swimmerA: CorridorSwimmer(
                name: nameA,
                yearOfBirth: yobA ?? 2008,
                country: selection.country,
                gender: selection.gender.rawValue,
                points: demoSwimmerPoints
            ),
            swimmerB: CorridorSwimmer(
                name: nameB,
                yearOfBirth: yobB ?? 2009,
                country: countryB,
                gender: selection.gender.rawValue,
                points: demoSwimmerBPoints
            ),
            imageBase64: nil,
            missing: nil
        )
    }

    // MARK: - Demo data

    private static let demoSwimmers: [SwimmerSearchResult] = [
        SwimmerSearchResult(label: "DUPONT Alice (2008)", name: "DUPONT Alice", yearOfBirth: 2008, gender: "F", country: .FR),
        SwimmerSearchResult(label: "MARTIN Léa (2007)", name: "MARTIN Léa", yearOfBirth: 2007, gender: "F", country: .FR),
        SwimmerSearchResult(label: "BERNARD Hugo (2006)", name: "BERNARD Hugo", yearOfBirth: 2006, gender: "M", country: .FR),
        SwimmerSearchResult(label: "ALAMI Sara (2009)", name: "ALAMI Sara", yearOfBirth: 2009, gender: "F", country: .MA),
        SwimmerSearchResult(label: "BENALI Youssef (2005)", name: "BENALI Youssef", yearOfBirth: 2005, gender: "M", country: .MA),
        SwimmerSearchResult(label: "SMITH Emma (2008)", name: "SMITH Emma", yearOfBirth: 2008, gender: "F", country: .US),
    ]

    private static let demoBands: [CorridorBand] = [
        CorridorBand(age: 12, ageGroup: nil, n: 210, p10: 64.0, p25: 66.5, p50: 69.2, p75: 72.0, p90: 75.5),
        CorridorBand(age: 13, ageGroup: nil, n: 280, p10: 61.5, p25: 63.8, p50: 66.4, p75: 69.1, p90: 72.4),
        CorridorBand(age: 14, ageGroup: nil, n: 320, p10: 58.2, p25: 60.1, p50: 62.4, p75: 65.0, p90: 68.3),
        CorridorBand(age: 15, ageGroup: nil, n: 340, p10: 56.0, p25: 57.9, p50: 60.1, p75: 62.8, p90: 66.0),
        CorridorBand(age: 16, ageGroup: nil, n: 300, p10: 54.5, p25: 56.2, p50: 58.4, p75: 61.0, p90: 64.2),
        CorridorBand(age: 17, ageGroup: nil, n: 260, p10: 53.2, p25: 54.8, p50: 57.0, p75: 59.5, p90: 62.8),
        CorridorBand(age: 18, ageGroup: nil, n: 220, p10: 52.4, p25: 54.0, p50: 56.1, p75: 58.6, p90: 61.9),
    ]

    private static let demoSwimmerPoints: [SwimmerPoint] = [
        SwimmerPoint(age: 13, ageGroup: nil, timeS: 65.1),
        SwimmerPoint(age: 14, ageGroup: nil, timeS: 61.2),
        SwimmerPoint(age: 15, ageGroup: nil, timeS: 59.8),
        SwimmerPoint(age: 16, ageGroup: nil, timeS: 58.0),
    ]

    private static let demoSwimmerBPoints: [SwimmerPoint] = [
        SwimmerPoint(age: 13, ageGroup: nil, timeS: 66.8),
        SwimmerPoint(age: 14, ageGroup: nil, timeS: 63.0),
        SwimmerPoint(age: 15, ageGroup: nil, timeS: 61.5),
        SwimmerPoint(age: 16, ageGroup: nil, timeS: 59.9),
    ]

    private static func loadBundledCorridor() -> CorridorResponse? {
        guard let url = Bundle.main.url(forResource: "SampleCorridor", withExtension: "json"),
              let data = try? Data(contentsOf: url) else {
            return nil
        }
        return try? JSONDecoder().decode(CorridorResponse.self, from: data)
    }
}
