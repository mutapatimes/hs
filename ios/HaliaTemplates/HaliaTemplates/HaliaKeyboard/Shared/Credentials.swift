// Target membership: BOTH.
//
// The composer keyboard makes live calls (lookup, draft), so it needs the token and address at
// request time. With Full Access on, the keyboard reads them here from the App Group, which the
// host app writes on sync. This is a functional choice: for stronger secrecy, a shared Keychain
// access group is the hardening step, but the App Group is sandboxed to these two targets.
import Foundation

enum Credentials {
    static var token: String {
        get { AppGroup.defaults.string(forKey: AppGroup.Key.token) ?? "" }
        set { AppGroup.defaults.set(newValue, forKey: AppGroup.Key.token) }
    }

    static var baseURL: String {
        get { AppGroup.defaults.string(forKey: AppGroup.Key.baseURL) ?? "https://haliascore.com" }
        set { AppGroup.defaults.set(newValue, forKey: AppGroup.Key.baseURL) }
    }

    /// The signed-in seat's name (empty on the legacy shared token). Shown as "Signed in as …".
    static var name: String {
        get { AppGroup.defaults.string(forKey: AppGroup.Key.name) ?? "" }
        set { AppGroup.defaults.set(newValue, forKey: AppGroup.Key.name) }
    }

    static var hasToken: Bool { !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    /// Clear all credentials on sign-out.
    static func clear() {
        for k in [AppGroup.Key.token, AppGroup.Key.baseURL, AppGroup.Key.name] {
            AppGroup.defaults.removeObject(forKey: k)
        }
    }
}
