// Target membership: BOTH.
//
// One outreach template, matching the JSON that /v1/extension/context returns:
//   { "name": ..., "category": ..., "subject": ..., "body": ... }
// The server already fills {sender} and {catalog_link}; it leaves {first_name} as a literal
// token for the client-facing surface to fill. This keyboard fills it locally.
import Foundation

struct Template: Codable, Identifiable, Hashable {
    let name: String
    let category: String
    let subject: String
    let body: String

    var id: String { category + "|" + name }

    private enum CodingKeys: String, CodingKey { case name, category, subject, body }

    init(name: String, category: String, subject: String, body: String) {
        self.name = name
        self.category = category.isEmpty ? "General" : category
        self.subject = subject
        self.body = body
    }

    // Tolerant decode: missing or null fields become empty rather than failing the whole sync.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let cat = (try c.decodeIfPresent(String.self, forKey: .category)) ?? ""
        name = (try c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        category = cat.isEmpty ? "General" : cat
        subject = (try c.decodeIfPresent(String.self, forKey: .subject)) ?? ""
        body = (try c.decodeIfPresent(String.self, forKey: .body)) ?? ""
    }

    /// The text to drop into a chat. Body is the message; fall back to subject if a template has none.
    var insertBase: String {
        let b = body.trimmingCharacters(in: .whitespacesAndNewlines)
        return b.isEmpty ? subject : body
    }

    /// A one-line preview for the list.
    var preview: String {
        insertBase
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespaces)
    }

    /// Ready to drop into a chat. The one placeholder the server leaves, {first_name}, is removed
    /// (never a stored name, so never the wrong one), and the small gap it leaves is tidied so the
    /// line still reads cleanly. You add the name yourself in the chat if you want to.
    var readyToInsert: String {
        var s = insertBase.replacingOccurrences(of: "{first_name}", with: "")
        // Close up the space and punctuation the removed name left behind.
        for (bad, good) in [(" ,", ","), (" .", "."), (" !", "!"), (" ?", "?")] {
            s = s.replacingOccurrences(of: bad, with: good)
        }
        while s.contains("  ") { s = s.replacingOccurrences(of: "  ", with: " ") }
        s = s.trimmingCharacters(in: .whitespacesAndNewlines)
        // A template that led with the name now starts with a stray comma; drop it and, only in
        // that case, re-capitalise the sentence that is now first. We do NOT touch capitalisation
        // otherwise, so a template that opens with a URL (e.g. just {catalog_link}) is left alone
        // rather than mangled into "Https://".
        if s.hasPrefix(",") {
            s.removeFirst()
            s = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if let i = s.firstIndex(where: { $0.isLetter }) {
                s.replaceSubrange(i...i, with: s[i].uppercased())
            }
        }
        return s
    }
}
