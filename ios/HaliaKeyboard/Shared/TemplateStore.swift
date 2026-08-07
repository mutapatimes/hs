// Target membership: BOTH.
//
// The bridge between the two targets. The host app calls save(...) after a sync; the keyboard
// calls load() at display time. Everything lives in the App Group so the keyboard needs no
// network and no Full Access.
import Foundation

enum TemplateStore {

    static func save(_ templates: [Template]) {
        if let data = try? JSONEncoder().encode(templates) {
            AppGroup.defaults.set(data, forKey: AppGroup.Key.templates)
            AppGroup.defaults.set(Date(), forKey: AppGroup.Key.syncedAt)
        }
    }

    static func load() -> [Template] {
        guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.templates),
              let templates = try? JSONDecoder().decode([Template].self, from: data)
        else { return [] }
        return templates
    }

    /// The categories present, in a stable A–Z order, for the keyboard's filter chips.
    static func categories() -> [String] {
        let all = Set(load().map { $0.category })
        return all.sorted()
    }

    static var syncedAt: Date? {
        AppGroup.defaults.object(forKey: AppGroup.Key.syncedAt) as? Date
    }
}
