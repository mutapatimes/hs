// Target membership: HaliaTemplates (host app) AND HaliaCallDirectory (the Call Directory ext).
//
// The VIP caller-ID list, shared through the App Group: the host app fetches it from
// /v1/extension/directory and writes it here; the Call Directory extension reads it when iOS asks
// it to (re)load. This is the one place a small set of client numbers is cached on the merchant's
// own device; DirectoryStore.clear() wipes it on sign-out. The service itself still stores nothing.
import Foundation

enum DirectoryStore {
    /// One caller-ID entry: a full-international number (country code, no plus) and its label.
    struct Entry: Codable {
        let number: Int64
        let label: String
    }

    /// Save the list, de-duplicated and sorted ascending by number (CallKit's requirement).
    static func save(_ entries: [Entry]) {
        var seen = Set<Int64>()
        let clean = entries
            .filter { seen.insert($0.number).inserted }
            .sorted { $0.number < $1.number }
        if let data = try? JSONEncoder().encode(clean) {
            AppGroup.defaults.set(data, forKey: AppGroup.Key.directory)
        }
    }

    /// The stored list, already sorted ascending. Empty if never synced or signed out.
    static func load() -> [Entry] {
        guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.directory),
              let entries = try? JSONDecoder().decode([Entry].self, from: data) else { return [] }
        return entries
    }

    static func clear() {
        AppGroup.defaults.removeObject(forKey: AppGroup.Key.directory)
    }
}
