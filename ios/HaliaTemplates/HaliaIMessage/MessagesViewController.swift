// Target membership: HaliaIMessage ONLY.
//
// Halia in the Messages drawer. Compact, it is one button. Expanded, a Messages extension gets
// close to a full screen, so the desk that follows carries what the keyboard carries and more:
// who the message is for, the house notes, the range, a drafted note, and booking a visit.
//
// Everything it puts in the conversation is plain text or a plain link, never a Halia message
// bubble: a bubble would offer the App Store to anyone without the app, and no client installs a
// boutique's app. A selection link carries preview tags, so it arrives as an image card and opens
// a page where the client ticks what they like. Their picks come back to whoever sent it.
import Messages
import SwiftUI
import UIKit

final class MessagesViewController: MSMessagesAppViewController {
    private var hosting: UIHostingController<AnyView>?
    private var style: MSMessagesAppPresentationStyle = .compact

    override func willBecomeActive(with conversation: MSConversation) {
        super.willBecomeActive(with: conversation)
        present(for: presentationStyle)
    }

    override func willTransition(to presentationStyle: MSMessagesAppPresentationStyle) {
        super.willTransition(to: presentationStyle)
        present(for: presentationStyle)
    }

    private func present(for style: MSMessagesAppPresentationStyle) {
        // Rebuilding the desk on every transition would throw away a lookup and a half-written
        // draft, so the expanded view is built once and kept.
        if style == self.style, hosting != nil { return }
        self.style = style
        hosting?.willMove(toParent: nil)
        hosting?.view.removeFromSuperview()
        hosting?.removeFromParent()

        let root: AnyView
        if !Credentials.hasToken {
            root = AnyView(SignedOutView())
        } else if style == .compact {
            root = AnyView(CompactView { [weak self] in self?.requestPresentationStyle(.expanded) })
        } else {
            root = AnyView(DeskView(
                insert: { [weak self] text in self?.activeConversation?.insertText(text) { _ in } },
                collapse: { [weak self] in self?.requestPresentationStyle(.compact) }))
        }

        let vc = UIHostingController(rootView: root)
        addChild(vc)
        vc.view.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(vc.view)
        NSLayoutConstraint.activate([
            vc.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            vc.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            vc.view.topAnchor.constraint(equalTo: view.topAnchor),
            vc.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        vc.didMove(toParent: self)
        hosting = vc
    }
}

// MARK: - The two small states

private struct SignedOutView: View {
    var body: some View {
        VStack(spacing: 8) {
            Text("Halia").font(.headline)
            Text("Open the Halia app and sign in to write from here.")
                .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(20)
    }
}

private struct CompactView: View {
    let expand: () -> Void
    var body: some View {
        Button(action: expand) {
            HStack(spacing: 8) {
                Image(systemName: "square.grid.2x2")
                Text("Open your desk").fontWeight(.semibold)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 12).fill(Ink.brand))
            .foregroundColor(.white)
        }
        .padding(14)
    }
}
