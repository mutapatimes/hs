// Target membership: HOST APP ONLY.
//
// The one network call this whole product makes: GET /v1/extension/context with the extension
// token, and pull the merchant's templates out of it. Same endpoint the browser extension uses.
import Foundation

enum HaliaAPIError: LocalizedError {
    case badURL
    case unauthorized
    case http(Int)
    case decode
    case network(String)

    var errorDescription: String? {
        switch self {
        case .badURL:       return "That Halia address does not look right."
        case .unauthorized: return "Token not recognised. Generate a new one in Halia, Settings."
        case .http(let c):  return "Halia returned an error (HTTP \(c))."
        case .decode:       return "Could not read the response from Halia."
        case .network(let m): return "Could not reach Halia. \(m)"
        }
    }
}

struct HaliaAPI {
    var baseURL: String
    var token: String

    private struct ContextResponse: Decodable { let templates: [Template]? }

    func fetchTemplates() async throws -> [Template] {
        let trimmed = baseURL
            .trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: trimmed + "/v1/extension/context") else {
            throw HaliaAPIError.badURL
        }

        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.setValue(token, forHTTPHeaderField: "X-Halia-Ext-Token")
        req.timeoutInterval = 20

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse else { throw HaliaAPIError.decode }
            if http.statusCode == 401 { throw HaliaAPIError.unauthorized }
            guard (200..<300).contains(http.statusCode) else { throw HaliaAPIError.http(http.statusCode) }
            guard let decoded = try? JSONDecoder().decode(ContextResponse.self, from: data) else {
                throw HaliaAPIError.decode
            }
            return decoded.templates ?? []
        } catch let e as HaliaAPIError {
            throw e
        } catch {
            throw HaliaAPIError.network(error.localizedDescription)
        }
    }
}
