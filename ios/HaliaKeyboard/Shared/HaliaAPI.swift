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
        case .http(let c):    return "Halia returned an error (HTTP \(c))."
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

    private struct ContextResponse: Decodable { let templates: [Template]? }

    func fetchTemplates() async throws -> [Template] {
        let (data, _) = try await send("/v1/extension/context", method: "GET", body: nil)
        guard let decoded = try? JSONDecoder().decode(ContextResponse.self, from: data) else {
            throw HaliaAPIError.decode
        }
        return decoded.templates ?? []
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
        private enum K: String, CodingKey { case found, name, cid, cart }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: K.self)
            found = (try? c.decodeIfPresent(Bool.self, forKey: .found)) ?? nil
            name  = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? nil
            cid   = (try? c.decodeIfPresent(Scalar.self, forKey: .cid))?.text   // cid may be number or string
            cart  = (try? c.decodeIfPresent(Cart.self, forKey: .cart)) ?? nil
        }
    }

    func lookup(_ ref: ClientRef) async throws -> LookupResult {
        try await postJSON("/v1/extension/lookup", body: ref.body)
    }

    // MARK: Draft (keyboard) — a personal message for the client, in the house voice. An optional
    // thread (the client's copied message) makes the reply responsive.

    struct DraftResult: Decodable { let draft: String?; let name: String?; let found: Bool? }

    func draft(_ ref: ClientRef, channel: String, instruction: String,
               thread: [[String: String]]? = nil) async throws -> DraftResult {
        var body: [String: Any] = ref.body
        body["channel"] = channel
        body["instruction"] = instruction
        if let thread = thread, !thread.isEmpty { body["thread"] = thread }
        return try await postAny("/v1/extension/draft", body: body)
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

    func catalogue(productIds: [String], name: String?) async throws -> String {
        let body: [String: Any] = ["product_ids": productIds, "name": name ?? ""]
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
