// Target membership: HaliaTemplates (host app), the HaliaKeyboard extension (which reads the
// shortlist and builds the catalogue), and any other extension that saves/reads it.
//
// The "save while you browse" shortlist, shared through the App Group: products the associate saves
// from Safari / the share sheet accumulate here (URL + optional title), and Build-a-catalogue turns
// them into a link. On-device only, cleared on sign-out or after a catalogue is built. Halia the
// service stores nothing; the products travel in the signed catalogue link.
import Foundation

enum SavedItemsStore {
    struct Item: Codable, Equatable {
        let url: String
        let title: String?
        let at: Date
    }

    static func load() -> [Item] {
        guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.saved),
              let items = try? JSONDecoder().decode([Item].self, from: data) else { return [] }
        return items
    }

    /// Add a product URL (de-duplicated by URL, newest kept). Returns the new count.
    @discardableResult
    static func add(_ url: String, title: String? = nil) -> Int {
        let u = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !u.isEmpty else { return count }
        var items = load().filter { $0.url != u }
        items.append(Item(url: u, title: title, at: Date()))
        save(items)
        return items.count
    }

    static func urls() -> [String] { load().map { $0.url } }

    static var count: Int { load().count }

    static func clear() { AppGroup.defaults.removeObject(forKey: AppGroup.Key.saved) }

    private static func save(_ items: [Item]) {
        if let data = try? JSONEncoder().encode(Array(items.suffix(60))) {   // cap the shortlist
            AppGroup.defaults.set(data, forKey: AppGroup.Key.saved)
        }
    }
}
