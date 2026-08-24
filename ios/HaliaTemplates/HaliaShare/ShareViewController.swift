// Target membership: HaliaShare (the Share extension) ONLY.
// Also add the Shared/ files to this target: HaliaAPI, Credentials, AppGroup, ClientRef.
//
// "Send with Halia" — share a client's name / email / phone from Contacts, Messages, Safari or the
// Shopify app, and this looks them up (grade, why, open basket) and drafts a message you can copy
// straight back into the chat. Hosts the SwiftUI card below.
import UIKit
import SwiftUI
import UniformTypeIdentifiers
import Contacts

class ShareViewController: UIViewController {

    override func viewDidLoad() {
        super.viewDidLoad()
        extractSharedText { [weak self] text in
            guard let self = self else { return }
            let root = ShareRootView(
                query: text ?? "",
                onOpen: { [weak self] url, completion in
                    guard let self, let ctx = self.extensionContext else { completion(false); return }
                    ctx.open(url, completionHandler: completion)
                },
                onClose: { [weak self] in self?.finish() })
            let host = UIHostingController(rootView: root)
            host.view.backgroundColor = .clear
            self.addChild(host)
            host.view.frame = self.view.bounds
            host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            self.view.addSubview(host.view)
            host.didMove(toParent: self)
        }
    }

    private func finish() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    /// The best lookup identifier among the shared attachments: a shared contact (vCard) first, then
    /// plain text, then a URL.
    private func extractSharedText(_ completion: @escaping (String?) -> Void) {
        let providers = (extensionContext?.inputItems as? [NSExtensionItem])?
            .compactMap { $0.attachments }.flatMap { $0 } ?? []
        let vcardType = UTType.vCard.identifier
        let textType = UTType.plainText.identifier
        let urlType = UTType.url.identifier
        func done(_ s: String?) {
            DispatchQueue.main.async {
                completion(s?.trimmingCharacters(in: .whitespacesAndNewlines))
            }
        }
        if let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier(vcardType) }) {
            p.loadItem(forTypeIdentifier: vcardType, options: nil) { item, _ in done(Self.queryFromVCard(item)) }
        } else if let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier(textType) }) {
            p.loadItem(forTypeIdentifier: textType, options: nil) { data, _ in done(data as? String) }
        } else if let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier(urlType) }) {
            p.loadItem(forTypeIdentifier: urlType, options: nil) { data, _ in
                done((data as? URL)?.absoluteString ?? data as? String)
            }
        } else {
            done(nil)
        }
    }

    /// Pull the best lookup identifier out of a shared contact card: a phone (so the send buttons
    /// work too), else an email, else the full name. Parsing a vCard needs no Contacts permission.
    private static func queryFromVCard(_ item: Any?) -> String? {
        let data: Data?
        switch item {
        case let d as Data:   data = d
        case let u as URL:    data = try? Data(contentsOf: u)
        case let s as String: data = s.data(using: .utf8)
        default:              data = nil
        }
        guard let data,
              let contact = (try? CNContactVCardSerialization.contacts(with: data))?.first
        else { return nil }

        if let phone = contact.phoneNumbers.first?.value.stringValue {
            // Normalise to +digits so ClientClassifier reads it as a phone (a "(555) 123-4567" would
            // otherwise fail its leading-digit check and be treated as a name).
            let cleaned = phone.filter { $0.isNumber || $0 == "+" }
            if cleaned.filter(\.isNumber).count >= 6 { return cleaned }
        }
        if let email = contact.emailAddresses.first?.value as String?, !email.isEmpty { return email }
        let name = [contact.givenName, contact.familyName].filter { !$0.isEmpty }.joined(separator: " ")
        return name.isEmpty ? nil : name
    }
}
