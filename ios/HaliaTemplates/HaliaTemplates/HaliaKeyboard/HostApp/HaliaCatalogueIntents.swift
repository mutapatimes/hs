// Target membership: HaliaTemplates (the host app) ONLY. Reuses Shared/ (HaliaAPI, Credentials,
// SavedItemsStore). These App Intents let an associate browse their store in Safari and — from the
// share sheet, the Action button, Shortcuts or Siri — save products, then build a catalogue or send
// one to a client, without ever opening the Halia app. Nothing is stored server-side.
import Foundation
import AppIntents
import UIKit

@available(iOS 16.0, *)
struct HaliaIntentError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

// MARK: Save a product while browsing

@available(iOS 16.0, *)
struct SaveItemIntent: AppIntent {
    static var title: LocalizedStringResource = "Save a product to Halia"
    static var description = IntentDescription(
        "Save a product you're viewing to your Halia list, to build a catalogue or send later.")
    static var openAppWhenRun = false

    @Parameter(title: "Product link")
    var url: URL

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard Credentials.hasToken else {
            throw HaliaIntentError(message: "Open Halia and connect your store first.")
        }
        let n = SavedItemsStore.add(url.absoluteString)
        return .result(dialog: "Saved. \(n) item\(n == 1 ? "" : "s") in your Halia list.")
    }
}

// MARK: Build a catalogue from the saved list

@available(iOS 16.0, *)
struct BuildCatalogueIntent: AppIntent {
    static var title: LocalizedStringResource = "Build a Halia catalogue"
    static var description = IntentDescription(
        "Turn the products you've saved into a shareable catalogue link, optionally addressed to a client.")
    static var openAppWhenRun = false

    @Parameter(title: "For (client name)", default: "")
    var client: String

    @MainActor
    func perform() async throws -> some IntentResult & ReturnsValue<URL> & ProvidesDialog {
        guard Credentials.hasToken else {
            throw HaliaIntentError(message: "Open Halia and connect your store first.")
        }
        let urls = SavedItemsStore.urls()
        guard !urls.isEmpty else {
            throw HaliaIntentError(message: "Your Halia list is empty. Save some products first.")
        }
        let r = try await HaliaAPI.current.catalogueFromUrls(urls: urls, name: client)
        guard !r.url.isEmpty, let link = URL(string: r.url) else {
            throw HaliaIntentError(message: "None of your saved products are in this store's catalogue.")
        }
        UIPasteboard.general.string = r.url
        let who = client.isEmpty ? "" : " for \(client)"
        return .result(value: link,
            dialog: "Catalogue ready\(who) with \(r.resolved) piece\(r.resolved == 1 ? "" : "s"), link copied.")
    }
}

// MARK: Send one product to a client

@available(iOS 16.0, *)
struct SendProductIntent: AppIntent {
    static var title: LocalizedStringResource = "Send a product with Halia"
    static var description = IntentDescription(
        "Turn the product you're viewing into a branded link to send a client.")
    static var openAppWhenRun = false

    @Parameter(title: "Product link")
    var url: URL

    @Parameter(title: "For (client name)", default: "")
    var client: String

    @MainActor
    func perform() async throws -> some IntentResult & ReturnsValue<URL> & ProvidesDialog {
        guard Credentials.hasToken else {
            throw HaliaIntentError(message: "Open Halia and connect your store first.")
        }
        let r = try await HaliaAPI.current.catalogueFromUrls(urls: [url.absoluteString], name: client)
        guard !r.url.isEmpty, let link = URL(string: r.url) else {
            throw HaliaIntentError(message: "That product isn't in this store's catalogue.")
        }
        UIPasteboard.general.string = r.url
        return .result(value: link, dialog: "Link ready, copied to send.")
    }
}

// MARK: How many saved / clear

@available(iOS 16.0, *)
struct SavedCountIntent: AppIntent {
    static var title: LocalizedStringResource = "Halia saved products"
    static var description = IntentDescription("How many products are on your Halia list.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let n = SavedItemsStore.count
        let message = n == 0 ? "Your Halia list is empty."
            : "You have \(n) product\(n == 1 ? "" : "s") saved."
        return .result(dialog: IntentDialog(stringLiteral: message))
    }
}

@available(iOS 16.0, *)
struct ClearSavedIntent: AppIntent {
    static var title: LocalizedStringResource = "Clear the Halia list"
    static var description = IntentDescription("Empty your saved-products list.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        SavedItemsStore.clear()
        return .result(dialog: "Cleared your Halia list.")
    }
}
