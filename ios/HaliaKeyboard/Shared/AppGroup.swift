// Target membership: BOTH (HaliaTemplates host app AND HaliaKeyboard extension).
//
// The App Group is the shared box the host app writes templates into and the keyboard reads
// from. It is what lets the keyboard work with NO network access and therefore NO "Full Access"
// permission. Set the SAME group id on both targets under Signing & Capabilities > App Groups,
// and put that exact id here.
import Foundation

enum AppGroup {
    /// CHANGE THIS to your own App Group id and set it on both targets. Must match exactly.
    static let identifier = "group.com.halia.templates"

    /// Shared defaults, scoped to the App Group. Falls back to standard defaults if the group
    /// id has not been configured yet (so the app still runs while you are wiring it up).
    static var defaults: UserDefaults {
        UserDefaults(suiteName: identifier) ?? .standard
    }

    enum Key {
        static let templates = "halia.templates.json"
        static let baseURL   = "halia.baseURL"
        static let syncedAt  = "halia.syncedAt"
    }
}
