// Target membership: BOTH.
//
// Store-info snippets: the small facts an associate pastes all day (hours, directions, returns, care,
// size guide, contact). The merchant types them once in the app; they live in the App Group and the
// keyboard shows them as a "Store info" category, inserted exactly like a template. No network, no
// backend, no client needed.
//
// (Team upgrade, later: sync these from the Halia backend so a whole team shares one set instead of
// each associate typing them.)
import Foundation

struct InfoSnippet: Codable, Identifiable {
    let label: String
    var value: String
    var id: String { label }
}

enum StoreInfoStore {
    /// The snippet slots the host app offers. Fixed for v1; covers the common ones.
    static let labels = ["My sign-off", "Opening hours", "Address & directions", "Returns policy",
                         "Product care", "Size guide", "Contact"]

    static let category = "Store info"

    static var snippets: [InfoSnippet] {
        get {
            guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.storeInfo),
                  let s = try? JSONDecoder().decode([InfoSnippet].self, from: data) else { return [] }
            return s
        }
        set {
            if let data = try? JSONEncoder().encode(newValue) {
                AppGroup.defaults.set(data, forKey: AppGroup.Key.storeInfo)
            }
        }
    }

    static func value(for label: String) -> String {
        snippets.first { $0.label == label }?.value ?? ""
    }

    /// Upsert one slot; an empty value removes it.
    static func set(_ value: String, for label: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        var all = snippets
        if let i = all.firstIndex(where: { $0.label == label }) {
            if trimmed.isEmpty { all.remove(at: i) } else { all[i].value = trimmed }
        } else if !trimmed.isEmpty {
            all.append(InfoSnippet(label: label, value: trimmed))
        }
        snippets = all
    }

    /// The filled snippets as insertable templates, so the keyboard treats them like any other.
    static func asTemplates() -> [Template] {
        snippets
            .filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            .map { Template(name: $0.label, category: category, subject: "", body: $0.value) }
    }
}
