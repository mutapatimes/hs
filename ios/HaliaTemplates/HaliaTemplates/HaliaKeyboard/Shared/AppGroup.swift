// Target membership: BOTH (HaliaTemplates host app AND HaliaKeyboard extension).
//
// The App Group is the shared box the host app writes templates into and the keyboard reads
// from. It is what lets the keyboard work with NO network access and therefore NO "Full Access"
// permission. Set the SAME group id on both targets under Signing & Capabilities > App Groups,
// and put that exact id here.
import Foundation

enum AppGroup {
    /// CHANGE THIS to your own App Group id and set it on both targets. Must match exactly.
    static let identifier = "group.com.haliascore.haliatemplates"

    /// Shared defaults, scoped to the App Group. Falls back to standard defaults if the group
    /// id has not been configured yet (so the app still runs while you are wiring it up).
    static var defaults: UserDefaults {
        UserDefaults(suiteName: identifier) ?? .standard
    }

    enum Key {
        static let templates = "halia.templates.json"
        static let storeInfo = "halia.storeinfo.json"
        static let baseURL   = "halia.baseURL"
        static let token     = "halia.token"
        static let name      = "halia.name"          // the signed-in seat's name (for "Signed in as …")
        static let syncedAt  = "halia.syncedAt"
        static let directory = "halia.directory.json"   // VIP caller-ID list for the Call Directory ext
        static let saved     = "halia.saved.json"        // shortlist of products saved while browsing
        static let openers   = "halia.openers.json"      // reverse-flow message openers (host app edits)
        static let hours     = "halia.hours.json"        // when the shop is open, from /context
    }
}

/// When the shop is open, as the store set it in Halia. Synced by the host app and read by the
/// keyboard, which otherwise offers every store on earth the same hard-coded 09:00-19:00.
/// Empty means the store has never said, and then nothing is bounded.
enum HoursStore {
    struct Day: Codable {
        let open: String        // "10:00"
        let close: String       // "18:00"
        let closed: Bool
    }

    /// Monday first, matching Calendar's `weekday` once it is shifted.
    static let keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    static func load() -> [String: Day] {
        guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.hours),
              let d = try? JSONDecoder().decode([String: Day].self, from: data) else { return [:] }
        return d
    }

    static func save(_ hours: [String: Day]) {
        guard let data = try? JSONEncoder().encode(hours) else { return }
        AppGroup.defaults.set(data, forKey: AppGroup.Key.hours)
    }

    /// The half-hourly slots a given day actually offers, as minutes past midnight. Falls back to
    /// the old 09:00-19:00 when the store has set no hours, and to nothing on a day it is shut.
    static func slots(on day: Date, step: Int = 30) -> [Int] {
        let fallback = Array(stride(from: 9 * 60, through: 19 * 60, by: step))
        let hours = load()
        guard !hours.isEmpty else { return fallback }
        // Calendar.weekday is 1 = Sunday; our keys start on Monday.
        let idx = (Calendar.current.component(.weekday, from: day) + 5) % 7
        guard let row = hours[keys[idx]], !row.closed else { return [] }
        guard let from = minutes(row.open), let to = minutes(row.close), to > from else {
            return fallback
        }
        return Array(stride(from: from, through: max(from, to - step), by: step))
    }

    static func minutes(_ hhmm: String) -> Int? {
        let parts = hhmm.split(separator: ":")
        guard let h = Int(parts.first ?? ""), h >= 0, h < 24 else { return nil }
        let m = parts.count > 1 ? (Int(parts[1]) ?? 0) : 0
        return h * 60 + max(0, min(m, 59))
    }
}
