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

    // MARK: Lookup (keyboard) — we take only the client's name; the grade is deliberately ignored.

    struct LookupResult: Decodable { let found: Bool?; let name: String? }

    func lookup(_ ref: ClientRef) async throws -> LookupResult {
        try await postJSON("/v1/extension/lookup", body: ref.body)
    }

    // MARK: Draft (keyboard) — a personal message for the client, in the house voice.

    struct DraftResult: Decodable { let draft: String?; let name: String?; let found: Bool? }

    func draft(_ ref: ClientRef, channel: String, instruction: String) async throws -> DraftResult {
        var body = ref.body
        body["channel"] = channel
        body["instruction"] = instruction
        return try await postJSON("/v1/extension/draft", body: body)
    }

    // MARK: Transport

    private func postJSON<T: Decodable>(_ path: String, body: [String: String]) async throws -> T {
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
