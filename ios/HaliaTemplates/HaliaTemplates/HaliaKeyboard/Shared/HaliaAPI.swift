// Target membership: BOTH.
//
// The Halia client. The host app uses fetchTemplates on sync; the composer keyboard uses lookup and
// draft live (which is why the keyboard now needs Full Access). All calls carry the extension token
// and hit the same /v1/extension/* endpoints the browser extension uses.
import Foundation

enum HaliaAPIError: LocalizedError {
    case badURL
    case unauthorized
    case http(Int)
    case decode
    case network(String)

    var errorDescription: String? {
        switch self {
        case .badURL:         return "That Halia address does not look right."
        case .unauthorized:   return "Token not recognised. Generate a new one in Halia, Settings."
        case .http(let c):
            if c == 402 { return "This store needs a plan for the extension and keyboard." }
            if c == 403 { return "Halia refused that request." }
            if c == 429 { return "Too many requests just now. A moment, then try again." }
            return "Halia returned an error (HTTP \(c))."
        case .decode:         return "Could not read the response from Halia."
        case .network(let m): return "Could not reach Halia. \(m)"
        }
    }
}

struct HaliaAPI {
    var baseURL: String
    var token: String

    /// Build the composer's client from the App Group credentials.
    static var current: HaliaAPI { HaliaAPI(baseURL: Credentials.baseURL, token: Credentials.token) }

    // MARK: Templates (host app, on sync)

    private struct ContextResponse: Decodable {
        let templates: [Template]?
        let seat: String?
        let hours: [String: HoursStore.Day]?
    }

    /// Templates, the signed-in seat name (nil on the legacy shared token), and when the shop is
    /// open, which the keyboard needs offline and so gets cached in the App Group on sync.
    func fetchContext() async throws -> (templates: [Template], seat: String?) {
        let (data, _) = try await send("/v1/extension/context", method: "GET", body: nil)
        guard let decoded = try? JSONDecoder().decode(ContextResponse.self, from: data) else {
            throw HaliaAPIError.decode
        }
        HoursStore.save(decoded.hours ?? [:])
        return (decoded.templates ?? [], decoded.seat)
    }

    func fetchTemplates() async throws -> [Template] { try await fetchContext().templates }

    /// Sign this device out (best effort): tells Halia the seat is going inactive.
    func signout() async {
        _ = try? await send("/v1/extension/signout", method: "POST", body: nil)
    }

    // MARK: Lookup (keyboard) — we take the name and cid; the grade is deliberately ignored.

    /// An open basket (abandoned checkout): how many items and the recovery link.
    struct Cart: Decodable {
        let count: Int?
        let url: String?
        private enum K: String, CodingKey { case count, url }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: K.self)
            url = (try? c.decodeIfPresent(String.self, forKey: .url)) ?? nil
            if let t = (try? c.decodeIfPresent(Scalar.self, forKey: .count))?.text {
                count = Int(Double(t) ?? 0)
            } else { count = nil }
        }
    }

    struct LookupResult: Decodable {
        let found: Bool?
        let name: String?
        let cid: String?
        let cart: Cart?
        // Richer fields the Share extension shows (the keyboard ignores them; hence all optional).
        let grade: String?
        let reasons: [String]?
        let latent: String?
        let action: String?
        let phone: String?           // the matched client's number, so a name lookup can still send
        let email: String?
        let suggested: [String]?     // template names ranked for this client (server-side)
        private enum K: String, CodingKey { case found, name, cid, cart, grade, reasons, latent, action, reco, phone, email, suggested }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: K.self)
            found = (try? c.decodeIfPresent(Bool.self, forKey: .found)) ?? nil
            name  = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? nil
            cid   = (try? c.decodeIfPresent(Scalar.self, forKey: .cid))?.text   // cid may be number or string
            cart  = (try? c.decodeIfPresent(Cart.self, forKey: .cart)) ?? nil
            phone = (try? c.decodeIfPresent(String.self, forKey: .phone)) ?? nil
            email = (try? c.decodeIfPresent(String.self, forKey: .email)) ?? nil
            suggested = (try? c.decodeIfPresent([String].self, forKey: .suggested)) ?? nil
            grade   = (try? c.decodeIfPresent(String.self, forKey: .grade)) ?? nil
            reasons = (try? c.decodeIfPresent([String].self, forKey: .reasons)) ?? nil
            latent  = (try? c.decodeIfPresent(Scalar.self, forKey: .latent))?.text
            action  = ((try? c.decodeIfPresent(String.self, forKey: .action)) ?? nil)
                        ?? ((try? c.decodeIfPresent(String.self, forKey: .reco)) ?? nil)
        }
    }

    func lookup(_ ref: ClientRef) async throws -> LookupResult {
        try await postJSON("/v1/extension/lookup", body: ref.body)
    }

    // MARK: Draft (keyboard) — a personal message for the client, in the house voice. An optional
    // thread (the client's copied message) makes the reply responsive.

    struct DraftResult: Decodable {
        let draft: String?; let name: String?; let found: Bool?
        let language: String?; let english: String?
    }

    func draft(_ ref: ClientRef, channel: String, instruction: String,
               thread: [[String: String]]? = nil) async throws -> DraftResult {
        var body: [String: Any] = ref.body
        body["channel"] = channel
        body["instruction"] = instruction
        if let thread = thread, !thread.isEmpty { body["thread"] = thread }
        return try await postAny("/v1/extension/draft", body: body)
    }

    // MARK: Brief (keyboard) — the client's copied message, read: what they want, a reply, next moves.

    struct BriefAction: Decodable { let kind: String?; let label: String? }
    struct BriefResult: Decodable {
        let summary: String?; let reply: String?; let urgency: String?
        let language: String?; let english: String?
        let actions: [BriefAction]?; let cid: String?; let name: String?
    }

    func brief(_ ref: ClientRef, channel: String, thread: [[String: String]]) async throws -> BriefResult {
        var body: [String: Any] = ref.body
        body["channel"] = channel
        body["thread"] = thread
        return try await postAny("/v1/extension/brief", body: body)
    }

    // MARK: Polish (keyboard) — the associate's own typed message, in the house voice.

    struct PolishResult: Decodable { let text: String?; let source: String? }

    func polish(text: String, ref: ClientRef?, greeting: Bool, signoff: Bool) async throws -> PolishResult {
        var body: [String: Any] = ref?.body ?? [:]
        body["text"] = text
        body["channel"] = "whatsapp"
        body["greeting"] = greeting
        body["signoff"] = signoff
        return try await postAny("/v1/extension/polish", body: body)
    }

    // MARK: Log contacted (keyboard) — write to the shared pipeline so the team is in the loop.

    private struct ActionResponse: Decodable { let recorded: Bool? }

    @discardableResult
    func logContacted(cid: String, clientName: String?, reason: String) async throws -> Bool {
        let body: [String: Any] = ["action": "contacted", "cid": cid,
                                   "client_name": clientName ?? "", "reason": reason]
        let resp: ActionResponse = try await postAny("/v1/extension/action", body: body)
        return resp.recorded ?? true
    }

    // MARK: Suggest (keyboard) — pieces to put in front of this client, chosen from your products.

    /// A number-or-string JSON scalar (Shopify prices arrive either way).
    private enum Scalar: Decodable {
        case string(String), number(Double), none
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if let s = try? c.decode(String.self) { self = .string(s) }
            else if let n = try? c.decode(Double.self) { self = .number(n) }
            else { self = .none }
        }
        var text: String? {
            switch self {
            case .string(let s): return s.isEmpty ? nil : s
            case .number(let n): return n.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(n)) : String(n)
            case .none: return nil
            }
        }
    }

    struct Pick: Decodable {
        let productId: String
        let title: String
        let why: String
        let priceText: String?

        private enum CodingKeys: String, CodingKey {
            case productId = "product_id", title, why, price, currency
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            productId = (try? c.decode(String.self, forKey: .productId)) ?? ""
            title = (try? c.decodeIfPresent(String.self, forKey: .title)) ?? "" ?? ""
            why = (try? c.decodeIfPresent(String.self, forKey: .why)) ?? "" ?? ""
            let price = (try? c.decodeIfPresent(Scalar.self, forKey: .price))?.text
            let currency = (try? c.decodeIfPresent(String.self, forKey: .currency)) ?? nil
            if let p = price {
                priceText = HaliaAPI.symbol(currency).map { $0 + p } ?? p
            } else {
                priceText = nil
            }
        }
    }

    private struct SuggestResponse: Decodable { let picks: [Pick]? }

    func suggest(_ ref: ClientRef, instruction: String) async throws -> [Pick] {
        var body = ref.body
        if !instruction.isEmpty { body["instruction"] = instruction }
        let resp: SuggestResponse = try await postJSON("/v1/extension/suggest", body: body)
        return resp.picks ?? []
    }

    private static func symbol(_ currency: String?) -> String? {
        switch (currency ?? "").uppercased() {
        case "GBP": return "£"
        case "USD", "CAD", "AUD": return "$"
        case "EUR": return "€"
        case "": return nil
        default: return (currency ?? "") + " "
        }
    }

    // MARK: Catalogue (keyboard) — mint a branded link for the chosen pieces.

    private struct CatalogueResponse: Decodable { let url: String? }

    /// The client's own details ride along so the page arrives filled in rather than asking them
    /// for what the store already holds. Prefill only.
    func catalogue(productIds: [String], name: String?,
                   email: String = "", phone: String = "") async throws -> String {
        let body: [String: Any] = ["product_ids": productIds, "name": name ?? "",
                                   "email": email, "phone": phone]
        let resp: CatalogueResponse = try await postAny("/v1/extension/catalogue", body: body)
        guard let url = resp.url, !url.isEmpty else { throw HaliaAPIError.decode }
        return url
    }

    /// A read-only Shopify cart permalink for the selection, so the client can pay in the chat.
    /// No write scope: the server just resolves variants and the domain.
    func cartLink(productIds: [String]) async throws -> String {
        let resp: CatalogueResponse = try await postAny("/v1/extension/cart_link",
                                                        body: ["product_ids": productIds])
        guard let url = resp.url, !url.isEmpty else { throw HaliaAPIError.decode }
        return url
    }

    // MARK: Product search (keyboard) — a live, searchable image library of the store's products.

    struct Product: Decodable {
        let id: String
        let title: String
        let handle: String?
        let image: String?
        private enum K: String, CodingKey { case id, title, handle, image }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: K.self)
            id     = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? "" ?? ""
            title  = (try? c.decodeIfPresent(String.self, forKey: .title)) ?? "" ?? ""
            handle = (try? c.decodeIfPresent(String.self, forKey: .handle)) ?? nil
            image  = (try? c.decodeIfPresent(String.self, forKey: .image)) ?? nil
        }
        var imageURL: URL? { image.flatMap { URL(string: $0) } }
        /// The shoppable product-page link, given the store's storefront base.
        func shareLink(cartBase: String?) -> String? {
            if let base = cartBase, let h = handle, !h.isEmpty {
                return base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/products/" + h
            }
            return image   // fall back to the raw image URL if we have no handle/domain
        }
    }

    /// The collections and sizes a view can be narrowed to.
    struct ProductFacets: Decodable {
        let collections: [String]?
        let sizes: [String]?
    }

    /// A view of the range: the page shown, everything it matches (so the whole view can go into
    /// one selection), and the filters to narrow it by.
    struct ProductView {
        let products: [Product]
        let cartBase: String?
        let ids: [String]
        let collections: [String]
        let sizes: [String]
    }

    private struct ProductSearch: Decodable {
        let products: [Product]?; let cart_base: String?
        let ids: [String]?; let facets: ProductFacets?
    }

    /// Live search of the merchant's catalogue (query on demand, like a GIF keyboard), narrowed to
    /// a collection or a size so an associate sends what actually suits the client.
    func searchProducts(_ q: String, limit: Int = 24, collection: String = "",
                        size: String = "") async throws -> ProductView {
        func enc(_ v: String) -> String { v.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "" }
        let path = "/v1/extension/products?q=\(enc(q))&limit=\(limit)"
            + "&collection=\(enc(collection))&size=\(enc(size))"
        let (data, _) = try await send(path, method: "GET", body: nil)
        guard let r = try? JSONDecoder().decode(ProductSearch.self, from: data) else { throw HaliaAPIError.decode }
        return ProductView(products: r.products ?? [], cartBase: r.cart_base, ids: r.ids ?? [],
                           collections: r.facets?.collections ?? [], sizes: r.facets?.sizes ?? [])
    }

    /// Resolve saved storefront URLs to product cards (with images) for the keyboard's Saved grid.
    func productsFromUrls(_ urls: [String]) async throws -> (products: [Product], cartBase: String?) {
        let (data, _) = try await send("/v1/extension/products_from_urls", method: "POST",
                                       body: try JSONSerialization.data(withJSONObject: ["urls": urls]))
        guard let r = try? JSONDecoder().decode(ProductSearch.self, from: data) else { throw HaliaAPIError.decode }
        return (r.products ?? [], r.cart_base)
    }



    // MARK: Today (widget + App Intents / Siri) — the proactive "who to reach today" queue.

    struct TodayItem: Decodable, Identifiable {
        let kind: String       // "new_order" | "gone_quiet"
        let name: String
        let grade: String
        let text: String
        let cid: String?
        private enum K: String, CodingKey { case kind, name, grade, text, cid }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: K.self)
            kind  = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "" ?? ""
            name  = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? "" ?? ""
            grade = (try? c.decodeIfPresent(String.self, forKey: .grade)) ?? "" ?? ""
            text  = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? "" ?? ""
            cid   = (try? c.decodeIfPresent(Scalar.self, forKey: .cid))?.text
        }
        var id: String { (cid ?? "") + kind + name }
        var isNewOrder: Bool { kind == "new_order" }

        /// Memberwise init for widget placeholders / previews (the Decodable init is used at runtime).
        init(kind: String, name: String, grade: String, text: String, cid: String?) {
            self.kind = kind; self.name = name; self.grade = grade; self.text = text; self.cid = cid
        }
    }

    private struct TodayResponse: Decodable { let label: String?; let count: Int?; let todos: [TodayItem]? }

    func today() async throws -> (label: String, items: [TodayItem]) {
        let (data, _) = try await send("/v1/extension/today", method: "GET", body: nil)
        guard let r = try? JSONDecoder().decode(TodayResponse.self, from: data) else { throw HaliaAPIError.decode }
        return (r.label ?? "Halia", r.todos ?? [])
    }

    // MARK: Directory (CallKit) — graded clients as full-international phone -> label for VIP caller ID.

    struct DirectoryEntry: Decodable {
        let phone: String        // E.164 digits, no plus (matches an incoming CXCallDirectoryPhoneNumber)
        let label: String
        let grade: String?
        var number: Int64? { Int64(phone) }
    }

    private struct DirectoryResponse: Decodable { let count: Int?; let entries: [DirectoryEntry]? }

    func directory() async throws -> [DirectoryEntry] {
        let (data, _) = try await send("/v1/extension/directory", method: "GET", body: nil)
        guard let r = try? JSONDecoder().decode(DirectoryResponse.self, from: data) else { throw HaliaAPIError.decode }
        return r.entries ?? []
    }

    // MARK: Client book (Share reverse flow) — pick who to send a shared product to.

    struct Client: Decodable, Identifiable {
        let cid: String?
        let name: String
        let grade: String
        let phone: String?
        let email: String?
        let latent: String?
        var id: String { (cid ?? "") + "|" + name }
        private enum K: String, CodingKey { case cid, name, grade, phone, email, latent }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: K.self)
            cid    = (try? c.decodeIfPresent(Scalar.self, forKey: .cid))?.text
            name   = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
            grade  = (try? c.decodeIfPresent(String.self, forKey: .grade)) ?? ""
            phone  = (try? c.decodeIfPresent(String.self, forKey: .phone)) ?? nil
            email  = (try? c.decodeIfPresent(String.self, forKey: .email)) ?? nil
            latent = (try? c.decodeIfPresent(Scalar.self, forKey: .latent))?.text
        }
    }

    private struct ClientsResponse: Decodable { let clients: [Client]? }

    /// The associate's client book, best clients first. Optional name search.
    func clients(q: String = "") async throws -> [Client] {
        let qs = q.isEmpty ? "" : "?q=" + (q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")
        let (data, _) = try await send("/v1/extension/clients" + qs, method: "GET", body: nil)
        guard let r = try? JSONDecoder().decode(ClientsResponse.self, from: data) else { throw HaliaAPIError.decode }
        return r.clients ?? []
    }

    // MARK: Catalogue from saved storefront URLs (App Intents "save while browsing").

    struct UrlCatalogueResult { let url: String; let resolved: Int; let requested: Int }
    private struct UrlCatalogueResponse: Decodable { let url: String?; let resolved: Int?; let requested: Int? }

    /// Resolve the saved storefront product URLs to a shareable catalogue link.
    func catalogueFromUrls(urls: [String], name: String = "", email: String = "",
                           phone: String = "") async throws -> UrlCatalogueResult {
        var body: [String: Any] = ["urls": urls]
        if !name.isEmpty { body["name"] = name }
        if !email.isEmpty { body["email"] = email }
        if !phone.isEmpty { body["phone"] = phone }
        let (data, _) = try await send("/v1/extension/catalogue_from_urls", method: "POST",
                                       body: try JSONSerialization.data(withJSONObject: body))
        guard let r = try? JSONDecoder().decode(UrlCatalogueResponse.self, from: data) else {
            throw HaliaAPIError.decode
        }
        return UrlCatalogueResult(url: r.url ?? "", resolved: r.resolved ?? 0, requested: r.requested ?? 0)
    }

    /// A Shopify /cart pay-in-chat link from the saved storefront URLs (empty if nothing is buyable).
    func cartLinkFromUrls(urls: [String]) async throws -> String {
        let (data, _) = try await send("/v1/extension/cart_link_from_urls", method: "POST",
                                       body: try JSONSerialization.data(withJSONObject: ["urls": urls]))
        guard let r = try? JSONDecoder().decode(UrlCatalogueResponse.self, from: data) else {
            throw HaliaAPIError.decode
        }
        return r.url ?? ""
    }

    // MARK: Client capture (handover)

    struct CaptureResult: Decodable { let ok: Bool?; let created: Bool?; let grade: String?; let customer_id: String? }

    /// Save a captured client straight into the store's Shopify (deduped, consent recorded,
    /// scored on the way through). Fields mirror POST /v1/capture.
    func captureClient(_ fields: [String: Any]) async throws -> CaptureResult {
        try await postAny("/v1/capture", body: fields)
    }

    private struct CaptureLink: Decodable { let url: String? }

    /// The store's self-capture URL (rendered as a QR the client scans on their own phone).
    func captureLink() async throws -> String {
        let (data, _) = try await send("/v1/capture/link", method: "GET", body: nil)
        guard let d = try? JSONDecoder().decode(CaptureLink.self, from: data), let u = d.url
        else { throw HaliaAPIError.decode }
        return u
    }

    /// Someone already in the book with this email or phone: enough to recognise them.
    struct ExistingClient: Decodable {
        let cid: String?; let name: String?; let email: String?; let phone: String?
        let orders: Int?; let spent: String?; let currency: String?; let last: String?; let by: String?
    }

    struct FieldCheck: Decodable {
        let email_ok: Bool?
        let email_suggestion: String?
        let postcode_ok: Bool?
        let postcode: String?
        let match: ExistingClient?
    }

    /// Live field hygiene for capture: a typo suggestion to offer before saving.
    func checkCapture(email: String?, postcode: String?, phone: String? = nil) async throws -> FieldCheck {
        var body: [String: Any] = [:]
        if let e = email, !e.isEmpty { body["email"] = e }
        if let p = postcode, !p.isEmpty { body["postcode"] = p }
        if let ph = phone, !ph.isEmpty { body["phone"] = ph }
        return try await postAny("/v1/capture/check", body: body)
    }

    // MARK: The associate's profile (name, email, position, sign-off) — lives on their seat.

    struct Profile: Decodable {
        let name: String?
        let email: String?
        let title: String?
        let signoff: String?
        let default_signoff: Bool?
    }
    private struct ProfileEnvelope: Decodable { let profile: Profile? }

    func fetchProfile() async throws -> Profile? {
        let (data, _) = try await send("/v1/extension/profile", method: "GET", body: nil)
        return (try? JSONDecoder().decode(ProfileEnvelope.self, from: data))?.profile
    }

    func saveProfile(name: String, email: String, title: String, signoff: String) async throws {
        let _: ProfileEnvelope = try await postAny("/v1/extension/profile",
            body: ["name": name, "email": email, "title": title, "signoff": signoff])
    }

    // MARK: The house voice — four sliders and a language, shared by everyone at this store.

    struct Voice: Codable {
        var formality: Int
        var exclusivity: Int
        var attentiveness: Int
        var polish: Int
        var language: String
    }
    struct VoiceAxis: Decodable { let key: String; let low: String; let high: String }
    struct VoiceLanguage: Decodable { let code: String; let name: String }
    struct VoiceSettings: Decodable {
        let voice: Voice?
        let sample: String?
        let axes: [VoiceAxis]?
        let languages: [VoiceLanguage]?
        let can_edit: Bool?          // the house voice belongs to the store, so only a manager moves it
        let role: String?
    }

    func fetchVoice() async throws -> VoiceSettings {
        let (data, _) = try await send("/v1/extension/voice", method: "GET", body: nil)
        guard let v = try? JSONDecoder().decode(VoiceSettings.self, from: data) else {
            throw HaliaAPIError.decode
        }
        return v
    }

    @discardableResult
    func saveVoice(_ v: Voice) async throws -> VoiceSettings {
        let body: [String: Any] = ["voice": ["formality": v.formality, "exclusivity": v.exclusivity,
                                             "attentiveness": v.attentiveness, "polish": v.polish,
                                             "language": v.language]]
        return try await postAny("/v1/extension/voice", body: body)
    }

    // MARK: Your week (the desk's own numbers)

    struct WeekRow: Decodable {
        let contacts: Int?
        let clients: Int?
        let captures: Int?
        let conversions: Int?
        let revenue: Int?
        let rate: Double?
    }
    struct Week: Decodable {
        let available: Bool?
        let days: Int?
        let me: WeekRow?
        let team: WeekRow?
    }

    func myWeek(days: Int = 7) async throws -> Week {
        let (data, _) = try await send("/v1/extension/week?days=\(days)", method: "GET", body: nil)
        guard let w = try? JSONDecoder().decode(Week.self, from: data) else { throw HaliaAPIError.decode }
        return w
    }

    // MARK: After a capture: the same-day follow-up, and birthdays coming up

    private struct OkOnly: Decodable { let ok: Bool? }

    /// Put a just-captured client on the pipeline's first column with a note.
    func captureFollowUp(customerId: String, note: String, due: String? = nil) async throws {
        var body: [String: Any] = ["customer_id": customerId, "note": note]
        if let due = due, !due.isEmpty { body["due"] = due }
        let _: OkOnly = try await postAny("/v1/capture/followup", body: body)
    }

    // MARK: Book a visit (keyboard) — into the client's own record, with the line to send them.

    struct BookedAppointment: Decodable { let ok: Bool?; let links: ApptLinks? }

    func bookAppointment(cid: String, when: String, place: String, clientName: String,
                         clientEmail: String = "", minutes: Int = 0) async throws -> BookedAppointment {
        // The client's address goes on the calendar entry beside the associate's, so both of them
        // hold the same invitation. `minutes` omitted lets the server apply the house default.
        var body: [String: Any] = ["action": "appointment", "cid": cid, "when": when,
                                   "place": place, "client_name": clientName,
                                   "client_email": clientEmail]
        if minutes > 0 { body["minutes"] = minutes }
        return try await postAny("/v1/extension/action", body: body)
    }

    // MARK: Remember (keyboard) — what the client said about themselves, into their record in the store.

    struct Occasion: Decodable { let label: String?; let date: String? }
    struct RememberResult: Decodable { let summary: String?; let occasion: Occasion?; let cid: String?; let saved: AnyDecodable? }
    struct AnyDecodable: Decodable { init(from decoder: Decoder) throws {} }

    func remember(text: String, ref: ClientRef) async throws -> RememberResult {
        var body: [String: Any] = ref.body
        body["text"] = text
        return try await postAny("/v1/extension/remember", body: body)
    }

    struct Birthday: Decodable {
        let cid: String?
        let name: String?
        let grade: String?
        let date: String?
        let in_days: Int?
    }
    private struct BirthdaysEnvelope: Decodable { let birthdays: [Birthday]? }

    struct ApptLinks: Decodable { let google: String?; let outlook: String?; let ics: String?; let invite: String?; let message: String? }
    struct Appointment: Decodable {
        let id: String?; let cid: String?; let name: String?; let when: String?; let minutes: Int?
        let place: String?; let seat_name: String?; let in_days: Int?; let mine: Bool?; let links: ApptLinks?
        let email: String?
    }

    /// Move a booking that is already in the client's record. It keeps its id, so the entry the
    /// client already has moves rather than a second one arriving.
    func moveAppointment(id: String, cid: String, when: String, place: String,
                         clientName: String, clientEmail: String) async throws -> BookedAppointment {
        let body: [String: Any] = ["action": "appointment_move", "id": id, "cid": cid, "when": when,
                                   "place": place, "client_name": clientName,
                                   "client_email": clientEmail]
        return try await postAny("/v1/extension/action", body: body)
    }

    @discardableResult
    func cancelAppointment(id: String, cid: String) async throws -> Bool {
        let body: [String: Any] = ["action": "appointment_cancel", "id": id, "cid": cid]
        let r: BookedAppointment = try await postAny("/v1/extension/action", body: body)
        return r.ok ?? false
    }
    private struct AppointmentsEnvelope: Decodable { let appointments: [Appointment]? }

    func appointments(days: Int = 14) async throws -> [Appointment] {
        let (data, _) = try await send("/v1/extension/appointments?days=\(days)", method: "GET", body: nil)
        return (try? JSONDecoder().decode(AppointmentsEnvelope.self, from: data))?.appointments ?? []
    }

    func birthdays(days: Int = 14) async throws -> [Birthday] {
        let (data, _) = try await send("/v1/extension/birthdays?days=\(days)", method: "GET", body: nil)
        return (try? JSONDecoder().decode(BirthdaysEnvelope.self, from: data))?.birthdays ?? []
    }

    // MARK: Transport

    private func postJSON<T: Decodable>(_ path: String, body: [String: String]) async throws -> T {
        try await postAny(path, body: body)
    }

    private func postAny<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        let payload = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await send(path, method: "POST", body: payload)
        guard let decoded = try? JSONDecoder().decode(T.self, from: data) else {
            throw HaliaAPIError.decode
        }
        return decoded
    }

    private func send(_ path: String, method: String, body: Data?) async throws -> (Data, HTTPURLResponse) {
        let trimmed = baseURL
            .trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: trimmed + path) else { throw HaliaAPIError.badURL }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(token, forHTTPHeaderField: "X-Halia-Ext-Token")
        if body != nil { req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        req.httpBody = body
        req.timeoutInterval = 20

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse else { throw HaliaAPIError.decode }
            if http.statusCode == 401 { throw HaliaAPIError.unauthorized }
            guard (200..<300).contains(http.statusCode) else { throw HaliaAPIError.http(http.statusCode) }
            return (data, http)
        } catch let e as HaliaAPIError {
            throw e
        } catch {
            throw HaliaAPIError.network(error.localizedDescription)
        }
    }
}

/// So an appointment can drive a SwiftUI sheet straight from the list.
extension HaliaAPI.Appointment: Identifiable {}
