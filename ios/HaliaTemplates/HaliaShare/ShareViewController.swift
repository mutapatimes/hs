// Target membership: HaliaShare (the Share extension) ONLY.
// Also add the Shared/ files to this target: HaliaAPI, Credentials, AppGroup, ClientRef.
//
// "Send with Halia" — share a client's name / email / phone from Contacts, Messages, Safari or the
// Shopify app, and this looks them up (grade, why, open basket) and drafts a message you can copy
// straight back into the chat. Hosts the SwiftUI card below.
import UIKit
import SwiftUI
import UniformTypeIdentifiers

class ShareViewController: UIViewController {

    override func viewDidLoad() {
        super.viewDidLoad()
        extractSharedText { [weak self] text in
            guard let self = self else { return }
            let root = ShareRootView(query: text ?? "") { [weak self] in self?.finish() }
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

    /// The first usable string among the shared attachments: plain text, else a URL.
    private func extractSharedText(_ completion: @escaping (String?) -> Void) {
        let providers = (extensionContext?.inputItems as? [NSExtensionItem])?
            .compactMap { $0.attachments }.flatMap { $0 } ?? []
        let textType = UTType.plainText.identifier
        let urlType = UTType.url.identifier
        func done(_ s: String?) {
            DispatchQueue.main.async {
                completion(s?.trimmingCharacters(in: .whitespacesAndNewlines))
            }
        }
        if let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier(textType) }) {
            p.loadItem(forTypeIdentifier: textType, options: nil) { data, _ in done(data as? String) }
        } else if let p = providers.first(where: { $0.hasItemConformingToTypeIdentifier(urlType) }) {
            p.loadItem(forTypeIdentifier: urlType, options: nil) { data, _ in
                done((data as? URL)?.absoluteString ?? data as? String)
            }
        } else {
            done(nil)
        }
    }
}
