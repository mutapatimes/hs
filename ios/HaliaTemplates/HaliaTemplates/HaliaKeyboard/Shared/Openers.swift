// Target membership: HOST APP (HaliaTemplates) AND HaliaShare.
//
// The reverse-flow message openers: the angles an associate reaches for when sending one piece to a
// client (set aside, just in, your taste…). The host app edits them; the Share extension reads them
// from the App Group. Falls back to a sensible default set when nothing has been saved.
import Foundation

struct Opener: Codable, Identifiable, Hashable {
    var label: String        // short chip name
    var body: String         // the message the catalogue link follows
    var id = UUID()

    private enum CodingKeys: String, CodingKey { case label, body }   // id is per-session, not stored
}

enum OpenersStore {
    static let defaults: [Opener] = [
        Opener(label: "Set aside",        body: "I have set this aside for you, if you would like it."),
        Opener(label: "Just in",          body: "This just arrived and I thought of you straight away."),
        Opener(label: "Your taste",       body: "This reminded me of your taste the moment it came in."),
        Opener(label: "What do you think", body: "I would love to know what you think of this."),
        Opener(label: "Limited",          body: "We have very few of these, and I wanted you to have first look."),
        Opener(label: "First look",       body: "An early look for you, before this goes out more widely."),
        Opener(label: "Back in stock",    body: "Good news, this piece is back. I can hold one for you."),
    ]

    static func load() -> [Opener] {
        guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.openers),
              let list = try? JSONDecoder().decode([Opener].self, from: data),
              !list.isEmpty else { return defaults }
        return list
    }

    /// Save, dropping any opener with an empty body or name. Empty overall falls back to defaults on load.
    static func save(_ openers: [Opener]) {
        let clean = openers.filter {
            !$0.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !$0.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        if let data = try? JSONEncoder().encode(clean) {
            AppGroup.defaults.set(data, forKey: AppGroup.Key.openers)
        }
    }

    static func reset() {
        AppGroup.defaults.removeObject(forKey: AppGroup.Key.openers)
    }
}
