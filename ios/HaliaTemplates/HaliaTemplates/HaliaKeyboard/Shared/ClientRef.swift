// Target membership: BOTH.
//
// Turns a copied string (a name, email, or phone number the associate copied in the chat) into a
// lookup query, mirroring the browser extension's queryFor(). This is how the keyboard learns who
// the message is for: the associate copies the client, and this classifies what they copied.
import Foundation

struct ClientRef: Equatable {
    enum Kind: String { case email, phone, name }
    let kind: Kind
    let value: String

    /// The JSON body the /lookup and /draft endpoints expect: {"email": …} / {"phone": …} / {"name": …}.
    var body: [String: String] { [kind.rawValue: value] }

    /// A best-effort first name from a copied full name, used only until a real lookup returns one.
    var provisionalFirstName: String {
        guard kind == .name else { return "" }
        return String(value.split(separator: " ").first ?? "")
    }
}

enum ClientClassifier {
    /// nil when there is nothing usable on the clipboard.
    static func classify(_ raw: String) -> ClientRef? {
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, t.count <= 120 else { return nil }
        if t.range(of: #"^[^@\s]+@[^@\s]+\.[^@\s]+$"#, options: .regularExpression) != nil {
            return ClientRef(kind: .email, value: t.lowercased())
        }
        if t.range(of: #"^\+?[\d][\d\s\-()]{6,}$"#, options: .regularExpression) != nil {
            let digits = t.filter { $0.isNumber || $0 == "+" }
            return ClientRef(kind: .phone, value: digits)
        }
        return ClientRef(kind: .name, value: t)
    }
}
