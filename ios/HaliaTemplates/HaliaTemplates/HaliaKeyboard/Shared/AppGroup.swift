// Target membership: BOTH (HaliaTemplates host app AND HaliaKeyboard extension).
//
// The App Group is the shared box the host app writes templates into and the keyboard reads
// from. It is what lets the keyboard work with NO network access and therefore NO "Full Access"
// permission. Set the SAME group id on both targets under Signing & Capabilities > App Groups,
// and put that exact id here.
import Foundation
#if canImport(UIKit)
import UIKit
import UniformTypeIdentifiers
#endif

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
        static let token     = "halia.token"         // legacy slot; the token now lives in the Keychain
        static let name      = "halia.name"          // the signed-in seat's name (for "Signed in as …")
        static let syncedAt  = "halia.syncedAt"
        static let directory = "halia.directory.json"   // VIP caller-ID list for the Call Directory ext
        static let saved     = "halia.saved.json"        // shortlist of products saved while browsing
        static let openers   = "halia.openers.json"      // reverse-flow message openers (host app edits)
        static let hours     = "halia.hours.json"        // when the shop is open, from /context
        static let burst     = "halia.burst.json"        // a burst in progress, shared with the keyboard + Messages
    }

    /// Everything in the shared box is a copy of what Halia holds (templates, the caller-ID list,
    /// a burst in progress) and is re-synced on demand, so none of it belongs in a backup of the
    /// phone. Called once by the host app at launch; the attribute sticks to the container.
    static func excludeFromBackup() {
        guard var url = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: identifier) else { return }
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
    }
}

#if canImport(UIKit)
/// Client messages and links go to the clipboard so the associate can paste them into a chat.
/// They are marked for this device only, so Universal Clipboard does not carry a client's name
/// and message onto a Mac or iPad, and they expire after a few minutes.
enum Clipboard {
    static let lifetime: TimeInterval = 10 * 60

    private static var options: [UIPasteboard.OptionsKey: Any] {
        [.localOnly: true, .expirationDate: Date().addingTimeInterval(lifetime)]
    }

    static func put(_ text: String) {
        UIPasteboard.general.setItems([[UTType.utf8PlainText.identifier: text]], options: options)
    }

    static func put(image: UIImage) {
        guard let data = image.pngData() else { return }
        UIPasteboard.general.setItems([[UTType.png.identifier: data]], options: options)
    }
}
#endif

/// A guided burst in progress: one template rendered per chosen client, sent by the associate
/// from their own apps, one at a time. The host app writes it, the keyboard and the Messages app
/// read it, so the queue follows the associate into whichever chat they open. It is transient:
/// cleared on Finish, ignored after a day, on this device only. Halia's server holds nothing.
enum BurstStore {
    struct Item: Codable {
        let cid: String
        let name: String
        let first: String
        let grade: String
        let email: String?
        let phone: String?          // full international digits, no plus; nil when unusable
        var message: String
        var subject: String?
        let consentEmail: String    // subscribed | not_subscribed | unknown
        let consentSms: String
        let warn: [String]
        let lastContactAt: String?
        let lastContactBy: String?
        var status: String          // pending | sent | skipped
        var text: String?           // the associate's own edit of the message, if any

        var body: String { text ?? message }
        var consentLine: String {
            func w(_ v: String) -> String { v == "subscribed" ? "subscribed" : v == "not_subscribed" ? "not subscribed" : "not on file" }
            if consentEmail == "unknown" && consentSms == "unknown" { return "Consent not on file" }
            return "Email \(w(consentEmail)) · SMS \(w(consentSms))"
        }
        var warnLine: String? {
            guard warn.contains("contacted_recently"), let at = lastContactAt else { return nil }
            let days: String
            if let d = ISO8601DateFormatter().date(from: at) ?? ISO8601DateFormatter.withFraction.date(from: at) {
                let n = Int(Date().timeIntervalSince(d) / 86400)
                days = n <= 0 ? "today" : n == 1 ? "yesterday" : "\(n) days ago"
            } else { days = "recently" }
            return "Contacted \(days)" + (lastContactBy.map { " by \($0)" } ?? "")
        }
    }

    struct Queue: Codable {
        let template: String
        let channel: String         // whatsapp | messages | email | line
        let started: Date
        var index: Int
        var items: [Item]
        var unreachable: Int        // skipped by the server: no address for the channel

        var current: Item? { index < items.count ? items[index] : nil }
        var sent: Int { items.filter { $0.status == "sent" }.count }
        var skipped: Int { unreachable + items.filter { $0.status == "skipped" }.count }
        var channelWord: String {
            switch channel { case "whatsapp": return "WhatsApp"; case "messages": return "Messages"
                             case "email": return "Mail"; case "line": return "LINE"; default: return channel }
        }
    }

    static func load() -> Queue? {
        guard let data = AppGroup.defaults.data(forKey: AppGroup.Key.burst),
              let q = try? JSONDecoder().decode(Queue.self, from: data),
              Date().timeIntervalSince(q.started) < 24 * 3600 else { return nil }
        return q
    }

    static func save(_ q: Queue) {
        guard let data = try? JSONEncoder().encode(q) else { return }
        AppGroup.defaults.set(data, forKey: AppGroup.Key.burst)
    }

    static func clear() { AppGroup.defaults.removeObject(forKey: AppGroup.Key.burst) }
}

extension ISO8601DateFormatter {
    static let withFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f
    }()
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
