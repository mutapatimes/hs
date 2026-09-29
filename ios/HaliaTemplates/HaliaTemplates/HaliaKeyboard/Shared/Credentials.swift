// Target membership: BOTH.
//
// The composer keyboard makes live calls (lookup, draft), so it needs the token and address at
// request time. The token lives in the Keychain, in an item shared through the App Group so the
// keyboard, the Share sheet and the Messages app read the same one the host app wrote. It is
// readable only after the device has been unlocked once and never leaves this device: it is not
// in any backup and does not migrate to a new phone. The address and the seat name are not
// secrets and stay in the shared defaults.
import Foundation
import Security

enum Credentials {
    static var token: String {
        get {
            if let t = Keychain.read(), !t.isEmpty { return t }
            // One-time move of a token an earlier version kept in the shared defaults.
            let old = AppGroup.defaults.string(forKey: AppGroup.Key.token) ?? ""
            if !old.isEmpty, Keychain.write(old) {
                AppGroup.defaults.removeObject(forKey: AppGroup.Key.token)
            }
            return old
        }
        set {
            let v = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if v.isEmpty {
                Keychain.delete()
                AppGroup.defaults.removeObject(forKey: AppGroup.Key.token)
            } else if Keychain.write(v) {
                AppGroup.defaults.removeObject(forKey: AppGroup.Key.token)
            } else {
                // The Keychain refused (a simulator without the entitlement, say): keep working.
                AppGroup.defaults.set(v, forKey: AppGroup.Key.token)
            }
        }
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
        Keychain.delete()
        for k in [AppGroup.Key.token, AppGroup.Key.baseURL, AppGroup.Key.name] {
            AppGroup.defaults.removeObject(forKey: k)
        }
    }
}

/// One generic-password item, shared across the app's targets through the App Group identifier,
/// which iOS accepts as a keychain access group without any further entitlement.
private enum Keychain {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.haliascore.halia",
         kSecAttrAccount as String: "seat-token",
         kSecAttrAccessGroup as String: AppGroup.identifier]
    }

    static func read() -> String? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func write(_ value: String) -> Bool {
        guard let data = value.data(using: .utf8) else { return false }
        let attrs: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let updated = SecItemUpdate(query as CFDictionary, attrs as CFDictionary)
        if updated == errSecSuccess { return true }
        if updated != errSecItemNotFound { return false }
        var q = query
        attrs.forEach { q[$0.key] = $0.value }
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }

    static func delete() {
        SecItemDelete(query as CFDictionary)
    }
}
