// Target membership: HaliaIMessage ONLY.
//
// Halia in the Messages drawer: pick pieces, send the client a selection they can tap through.
// What goes into the conversation is the plain catalogue link, not a Halia message bubble: a
// bubble would offer the App Store to anyone without the app, and no client installs a boutique's
// app. The link carries preview tags, so it arrives as an image card and opens a page where the
// client ticks what they like. Their picks come back to whoever sent it.
import Messages
import SwiftUI
import UIKit

final class MessagesViewController: MSMessagesAppViewController {
    private var hosting: UIHostingController<AnyView>?

    override func willBecomeActive(with conversation: MSConversation) {
        super.willBecomeActive(with: conversation)
        present(for: presentationStyle)
    }

    override func willTransition(to presentationStyle: MSMessagesAppPresentationStyle) {
        super.willTransition(to: presentationStyle)
        present(for: presentationStyle)
    }

    private func present(for style: MSMessagesAppPresentationStyle) {
        hosting?.willMove(toParent: nil)
        hosting?.view.removeFromSuperview()
        hosting?.removeFromParent()

        let root: AnyView
        if !Credentials.hasToken {
            root = AnyView(SignedOutView())
        } else if style == .compact {
            root = AnyView(CompactView { [weak self] in self?.requestPresentationStyle(.expanded) })
        } else {
            root = AnyView(PickerView(
                send: { [weak self] url in
                    self?.activeConversation?.insertText(url) { _ in }
                    self?.requestPresentationStyle(.compact)
                },
                close: { [weak self] in self?.requestPresentationStyle(.compact) }))
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

// MARK: - Views

private enum Ink {
    static let brand = Color(red: 0.122, green: 0.337, blue: 0.290)
    static let deep = Color(red: 0.055, green: 0.180, blue: 0.153)
    static let soft = Color(red: 0.380, green: 0.380, blue: 0.380)
}

private struct SignedOutView: View {
    var body: some View {
        VStack(spacing: 8) {
            Text("Halia").font(.headline)
            Text("Open the Halia app and sign in to send a selection.")
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
                Text("Build a selection").fontWeight(.semibold)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 12).fill(Ink.brand))
            .foregroundColor(.white)
        }
        .padding(14)
    }
}

/// Pick from what the associate saved while browsing, or search the catalogue, then send.
private struct PickerView: View {
    let send: (String) -> Void
    let close: () -> Void

    @State private var query = ""
    @State private var results: [HaliaAPI.Product] = []
    @State private var saved: [SavedItemsStore.Item] = []
    @State private var chosen: Set<String> = []
    @State private var busy = false
    @State private var status: String?

    /// Two sources, one list: what was saved while browsing until a search replaces it.
    private var fromSaved: Bool { results.isEmpty }
    private var rows: [(id: String, title: String)] {
        results.isEmpty ? saved.map { (id: $0.url, title: $0.title ?? $0.url) }
                        : results.map { (id: $0.id, title: $0.title) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TextField("Search your products", text: $query)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .onSubmit { Task { await search() } }
                Button("Search") { Task { await search() } }.font(.footnote.weight(.semibold))
                Button("Close", action: close).font(.footnote).foregroundStyle(.secondary)
            }
            .padding(12)

            if let status {
                Text(status).font(.footnote).foregroundStyle(.secondary).padding(.bottom, 8)
            }

            List(rows, id: \.id) { row in
                Button {
                    if chosen.contains(row.id) { chosen.remove(row.id) } else { chosen.insert(row.id) }
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: chosen.contains(row.id) ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(chosen.contains(row.id) ? Ink.brand : Color.secondary)
                        Text(row.title).lineLimit(2)
                        Spacer()
                    }
                }
                .buttonStyle(.plain)
            }
            .listStyle(.plain)

            Button {
                Task { await sendSelection() }
            } label: {
                Text(busy ? "Sending…" : "Send selection (\(chosen.count))")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(RoundedRectangle(cornerRadius: 12).fill(chosen.isEmpty ? Color.secondary.opacity(0.3) : Ink.brand))
                    .foregroundColor(.white)
            }
            .disabled(chosen.isEmpty || busy)
            .padding(12)
        }
        .task { saved = SavedItemsStore.load() }
    }

    private func search() async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        busy = true; status = nil
        do {
            results = try await HaliaAPI.current.searchProducts(q).products
            chosen.removeAll()
            if results.isEmpty { status = "Nothing matched that." }
        } catch {
            status = "Could not reach Halia."
        }
        busy = false
    }

    private func sendSelection() async {
        busy = true; status = nil
        do {
            let picked = rows.filter { chosen.contains($0.id) }.map { $0.id }
            let url = fromSaved
                ? try await HaliaAPI.current.catalogueFromUrls(urls: picked).url
                : try await HaliaAPI.current.catalogue(productIds: picked, name: nil)
            send(url)
        } catch {
            status = "Could not build that selection."
        }
        busy = false
    }
}
