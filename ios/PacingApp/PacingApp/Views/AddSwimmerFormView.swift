import SwiftUI

struct AddSwimmerFormView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss

    @State private var name: String = ""
    @State private var yearOfBirth: String = ""
    @State private var gender: String = "F"
    @State private var country: CountryCode = .MA
    @State private var club: String = ""
    @State private var stroke: StrokeCode = .FR
    @State private var distance: Int = 100
    @State private var pool: PoolCode = .LCM
    @State private var timeText: String = ""
    @State private var ageText: String = ""
    @State private var meetDate: Date = Date()
    @State private var includeMeetDate = true
    @State private var isSaving = false
    @State private var formError: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Nageur") {
                    TextField("Nom", text: $name)
                    TextField("Année de naissance", text: $yearOfBirth)
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif
                    Picker("Genre", selection: $gender) {
                        Text("Féminin").tag("F")
                        Text("Masculin").tag("M")
                        Text("Non renseigné").tag("")
                    }
                    Picker("Pays", selection: $country) {
                        ForEach(CountryCode.allCases) { code in
                            Text(code.label).tag(code)
                        }
                    }
                    TextField("Club (optionnel)", text: $club)
                }

                Section("Performance") {
                    Picker("Nage", selection: $stroke) {
                        ForEach(StrokeCode.allCases) { code in
                            Text(code.label).tag(code)
                        }
                    }
                    Picker("Distance", selection: $distance) {
                        ForEach(EventSelection.distances, id: \.self) { d in
                            Text("\(d) m").tag(d)
                        }
                    }
                    Picker("Bassin", selection: $pool) {
                        ForEach(PoolCode.allCases) { code in
                            Text(code.label).tag(code)
                        }
                    }
                    TextField("Temps (1:03.31 ou 63.31)", text: $timeText)
                        #if os(iOS)
                        .keyboardType(.decimalPad)
                        #endif
                    TextField("Âge à la course (si pas de date + année)", text: $ageText)
                        #if os(iOS)
                        .keyboardType(.decimalPad)
                        #endif
                    Toggle("Date de la course", isOn: $includeMeetDate)
                    if includeMeetDate {
                        DatePicker("Date", selection: $meetDate, displayedComponents: .date)
                    }
                }

                Section {
                    Text("Enregistrée dans data/processed/manual_performances. Une nouvelle course s’ajoute au même nageur.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let formError {
                    Section {
                        Text(formError).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Nouvelle performance")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Enregistrement…" : "Ajouter") {
                        Task { await save() }
                    }
                    .disabled(!canSave)
                }
            }
            .onAppear {
                stroke = store.selection.stroke
                distance = store.selection.distance
                pool = store.selection.pool
                country = store.selection.country
                if store.selection.gender != .all {
                    gender = store.selection.gender.rawValue
                }
                if let selected = store.selectedSwimmer {
                    name = selected.name
                    if let yob = selected.yearOfBirth {
                        yearOfBirth = String(yob)
                    }
                    if let g = selected.gender, g == "F" || g == "M" {
                        gender = g
                    }
                    country = selected.country
                }
            }
        }
    }

    private var canSave: Bool {
        !isSaving
            && !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && TimeFormat.parseToSeconds(timeText) != nil
    }

    private func save() async {
        formError = nil
        isSaving = true
        defer { isSaving = false }

        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let timeS = TimeFormat.parseToSeconds(timeText) else {
            formError = "Temps invalide. Exemple : 1:03.31 ou 63.31"
            return
        }
        let yob = Int(yearOfBirth.trimmingCharacters(in: .whitespacesAndNewlines))
        let age = Double(ageText.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: ",", with: "."))
        let dateString: String?
        if includeMeetDate {
            let fmt = DateFormatter()
            fmt.calendar = Calendar(identifier: .gregorian)
            fmt.locale = Locale(identifier: "en_US_POSIX")
            fmt.dateFormat = "yyyy-MM-dd"
            dateString = fmt.string(from: meetDate)
        } else {
            dateString = nil
        }
        if age == nil && (yob == nil || dateString == nil) {
            formError = "Indique l’âge, ou l’année de naissance et la date de la course."
            return
        }

        let genderValue = gender.isEmpty ? nil : gender
        let clubValue = club.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            _ = try await store.createPerformance(
                name: trimmedName,
                yearOfBirth: yob,
                gender: genderValue,
                country: country,
                club: clubValue.isEmpty ? nil : clubValue,
                stroke: stroke,
                distance: distance,
                pool: pool,
                timeS: timeS,
                meetDate: dateString,
                age: age
            )
            dismiss()
        } catch {
            formError = error.localizedDescription
        }
    }
}
