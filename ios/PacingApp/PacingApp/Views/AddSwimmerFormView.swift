import SwiftUI

struct AddSwimmerFormView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss

    @State private var name: String = ""
    @State private var yearOfBirth: String = ""
    @State private var gender: String = "F"
    @State private var country: CountryCode = .MA
    @State private var club: String = ""
    @State private var isSaving = false
    @State private var formError: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Identité") {
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

                Section {
                    Text("Enregistrement dans data/processed/manual_swimmers (via l’API si Live, sinon fichier local sur Mac).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let formError {
                    Section {
                        Text(formError).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Nouveau nageur")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Enregistrement…" : "Ajouter") {
                        Task { await save() }
                    }
                    .disabled(isSaving || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    private func save() async {
        formError = nil
        isSaving = true
        defer { isSaving = false }

        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let yob = Int(yearOfBirth.trimmingCharacters(in: .whitespacesAndNewlines))
        let genderValue = gender.isEmpty ? nil : gender
        let clubValue = club.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            _ = try await store.createSwimmer(
                name: trimmedName,
                yearOfBirth: yob,
                gender: genderValue,
                country: country,
                club: clubValue.isEmpty ? nil : clubValue
            )
            dismiss()
        } catch {
            formError = error.localizedDescription
        }
    }
}
