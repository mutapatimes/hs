// Target membership: HOST APP (HaliaTemplates) AND HaliaShare.
//
// The message openers offered when you share a page into Halia and pick a client. There is a set per
// page kind (a product, a collection, care, returns, and so on), so the note fits what you shared.
// The host app edits every set; the Share extension reads them from the App Group. Each kind falls
// back to a sensible default when nothing has been saved.
import Foundation

struct Opener: Codable, Identifiable, Hashable {
    var label: String        // short chip name
    var body: String         // the message the link follows
    var id = UUID()

    private enum CodingKeys: String, CodingKey { case label, body }   // id is per-session, not stored
}

/// What a shared URL is. Anything unrecognised is `.press` — a plain "thought of you" send.
enum PageKind: String, Codable, CaseIterable, Identifiable {
    case product, collection, care, returns, size, about, contact, press
    var id: String { rawValue }

    var title: String {
        switch self {
        case .product:    return "Product"
        case .collection: return "Collection"
        case .care:       return "Care"
        case .returns:    return "Returns"
        case .size:       return "Size guide"
        case .about:      return "About the house"
        case .contact:    return "Visit and appointments"
        case .press:      return "A link from elsewhere"
        }
    }

    /// The heading over the client picker for this kind.
    var actionTitle: String {
        switch self {
        case .product:    return "Send this piece"
        case .collection: return "Send this edit"
        case .contact:    return "Invite a client"
        default:          return "Send this to a client"
        }
    }

    /// Only a product becomes a signed catalogue link; every other kind sends the page link as-is.
    var buildsCatalogue: Bool { self == .product }

    /// Classify a shared URL. nil when it is not a URL at all (a name or contact -> client mode).
    static func from(url raw: String) -> PageKind? {
        let u = raw.lowercased()
        guard u.contains("://") else { return nil }
        func any(_ words: [String]) -> Bool { words.contains { u.contains($0) } }
        if u.contains("/products/")    { return .product }
        if u.contains("/collections/") { return .collection }
        if any(["care-guide", "product-care", "garment-care", "/care"])   { return .care }
        if any(["return", "refund", "exchange"])                          { return .returns }
        if any(["size-guide", "size-chart", "sizing", "/size"])           { return .size }
        if any(["/about", "our-story", "the-house", "heritage", "/story"]) { return .about }
        if any(["contact", "find-us", "/stores", "location", "/visit", "appointment", "/book"]) { return .contact }
        return .press
    }
}

enum OpenersStore {
    static let defaults: [PageKind: [Opener]] = [
        // {title} becomes the product's own name, read from the shared link; without one it reads "this".
        .product: [
            Opener(label: "Set aside",        body: "I have set {title} aside for you, if you would like it."),
            Opener(label: "Just in",          body: "{title} just arrived and I thought of you straight away."),
            Opener(label: "Your taste",       body: "{title} reminded me of your taste the moment it came in."),
            Opener(label: "What do you think", body: "I would love to know what you think of {title}."),
            Opener(label: "Limited",          body: "We are down to the last few of {title}, and I wanted you to have first look."),
            Opener(label: "First look",       body: "An early look at {title} for you, before it goes out more widely."),
            Opener(label: "Back in stock",    body: "Good news, {title} is back. I can hold one for you."),
        ],
        .collection: [
            Opener(label: "An edit for you",  body: "I put together a few pieces I thought you would love."),
            Opener(label: "New season",       body: "The new season is in. Here is a first look, chosen with you in mind."),
        ],
        .care: [
            Opener(label: "Care guide",       body: "Here is how to care for your piece, so it lasts beautifully."),
        ],
        .returns: [
            Opener(label: "Returns",          body: "Here is everything on our returns and exchanges, in case it helps."),
            Opener(label: "Happy to help",    body: "Of course. Here are the details, and I am here if you need anything."),
        ],
        .size: [
            Opener(label: "Size guide",       body: "Our size guide, so you find the perfect fit. Tell me if you would like me to check."),
        ],
        .about: [
            Opener(label: "About us",         body: "A little about the house, and how we like to look after you."),
        ],
        .contact: [
            Opener(label: "Come see us",      body: "Come and see us whenever suits. Here are the details."),
            Opener(label: "Book a visit",     body: "I would love to set aside some time for you. Shall we arrange a private appointment?"),
        ],
        .press: [
            Opener(label: "Thought of you",   body: "Saw this and immediately thought of you."),
        ],
    ]

    static func load(_ kind: PageKind) -> [Opener] {
        guard let data = AppGroup.defaults.data(forKey: key(kind)),
              let list = try? JSONDecoder().decode([Opener].self, from: data),
              !list.isEmpty else { return defaults[kind] ?? [] }
        return list
    }

    /// Save one kind's set, dropping any opener with an empty name or body.
    static func save(_ openers: [Opener], for kind: PageKind) {
        let clean = openers.filter {
            !$0.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !$0.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        if let data = try? JSONEncoder().encode(clean) {
            AppGroup.defaults.set(data, forKey: key(kind))
        }
    }

    static func reset(_ kind: PageKind) { AppGroup.defaults.removeObject(forKey: key(kind)) }

    private static func key(_ kind: PageKind) -> String { AppGroup.Key.openers + "." + kind.rawValue }

    /// The shared page's own name, read from its URL slug ("/products/silk-twill-scarf" →
    /// "Silk Twill Scarf"). Empty when the URL gives nothing usable.
    static func pageTitle(from raw: String) -> String {
        guard let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)) else { return "" }
        let comps = url.pathComponents.filter { $0 != "/" }
        guard let ix = comps.firstIndex(where: { $0 == "products" || $0 == "collections" }),
              ix + 1 < comps.count else { return "" }
        let slug = comps[ix + 1].removingPercentEncoding ?? comps[ix + 1]
        let words = slug.split(whereSeparator: { $0 == "-" || $0 == "_" }).map(String.init)
        guard !words.isEmpty else { return "" }
        let name = words.map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
        return name.count <= 60 ? name : ""
    }

    /// Fill {title} in an opener body (defaults and the host app's edited openers alike). Without a
    /// usable title it reads "this", re-capitalised in case the token opened the sentence.
    static func fill(_ body: String, title: String) -> String {
        guard body.contains("{title}") else { return body }
        var out = body.replacingOccurrences(of: "{title}", with: title.isEmpty ? "this" : title)
        if title.isEmpty, let first = out.first { out = String(first).uppercased() + out.dropFirst() }
        return out
    }
}
