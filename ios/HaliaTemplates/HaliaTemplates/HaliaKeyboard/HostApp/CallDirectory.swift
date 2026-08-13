// Target membership: HaliaTemplates (the host app) ONLY. Reuses Shared/ (HaliaAPI, Credentials,
// DirectoryStore). Call CallDirectory.refresh() after a sync (and on sign-out) so the caller-ID
// extension has a fresh VIP list to load.
import Foundation
import CallKit

enum CallDirectory {
    /// The Call Directory extension's bundle identifier. Set this to the ext target's bundle id
    /// (host app id + ".HaliaCallDirectory") once you create the target in Xcode.
    static let extensionIdentifier = "com.haliascore.haliatemplates.HaliaCallDirectory"

    /// Pull the VIP list from Halia, store it in the App Group, and ask iOS to reload the extension.
    /// Signed out clears the list so no client numbers linger on the device.
    static func refresh() async {
        guard Credentials.hasToken else {
            DirectoryStore.clear()
            reload()
            return
        }
        do {
            let entries: [DirectoryStore.Entry] = try await HaliaAPI.current.directory().compactMap {
                guard let n = $0.number else { return nil }
                return DirectoryStore.Entry(number: n, label: $0.label)
            }
            DirectoryStore.save(entries)
            reload()
        } catch {
            // Keep the last good list on a transient failure.
        }
    }

    /// Ask iOS to reload the extension. No-op if the user hasn't enabled it in Settings ▸ Phone ▸
    /// Call Blocking & Identification (the completion carries that error, which we ignore).
    static func reload() {
        CXCallDirectoryManager.sharedInstance.reloadExtension(withIdentifier: extensionIdentifier) { _ in }
    }
}
