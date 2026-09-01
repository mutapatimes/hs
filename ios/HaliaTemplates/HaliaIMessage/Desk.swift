// Target membership: HaliaIMessage ONLY.
//
// The desk inside Messages. Expanded, a Messages extension gets close to a full screen, which is
// far more room than the keyboard has, so everything the keyboard does in pills and one cramped
// row is laid out properly here: who the message is for, the house templates, the range, a
// drafted note, and booking a visit.
//
// The one thing this surface cannot do is read the conversation. Messages never tells an extension
// who the other person is, so the client is named the same way the keyboard names them: the
// associate pastes or types it, and Halia looks them up.
import SwiftUI

enum Ink {
    static let brand = Color(red: 0.122, green: 0.337, blue: 0.290)
    static let deep = Color(red: 0.055, green: 0.180, blue: 0.153)
    static let soft = Color(red: 0.380, green: 0.380, blue: 0.380)
}

/// Who this conversation is with, and the two things every tab needs to do: put text in the chat,
/// and get out of the way afterwards.
@MainActor
final class DeskModel: ObservableObject {
    @Published var ref: ClientRef?
    @Published var name = ""
    @Published var cid: String?
    @Published var email = ""
    @Published var phone = ""
    @Published var cartURL: String?
    @Published var cartCount: Int?
    @Published var suggested: [String] = []
    @Published var looking = false
    @Published var lookupNote: String?

    let insert: (String) -> Void
    let collapse: () -> Void

    init(insert: @escaping (String) -> Void, collapse: @escaping () -> Void) {
        self.insert = insert
        self.collapse = collapse
    }

    var firstName: String { String(name.split(separator: " ").first ?? "") }
    var hasClient: Bool { ref != nil }

    /// Put it in the chat and step back, so the associate is looking at the conversation again
    /// rather than at us.
    func send(_ text: String) {
        guard !text.isEmpty else { return }
        insert(text)
        collapse()
    }

    func clear() {
        ref = nil; name = ""; cid = nil; email = ""; phone = ""
        cartURL = nil; cartCount = nil; suggested = []; lookupNote = nil
    }

    func look(up raw: String) async {
        guard let r = ClientClassifier.classify(raw) else {
            lookupNote = "Type their name, number or email."
            return
        }
        ref = r
        name = r.kind == .name ? r.value : ""
        cid = nil; cartURL = nil; cartCount = nil; suggested = []
        looking = true; lookupNote = nil
        do {
            let res = try await HaliaAPI.current.lookup(r)
            if let n = res.name, !n.isEmpty { name = n }
            cid = res.cid
            email = res.email ?? ""
            phone = res.phone ?? ""
            suggested = res.suggested ?? []
            if let u = res.cart?.url, !u.isEmpty { cartURL = u; cartCount = res.cart?.count }
            if res.found != true { lookupNote = "Not in the book yet. You can still write to them." }
        } catch {
            lookupNote = (error as? LocalizedError)?.errorDescription ?? "Could not reach Halia."
        }
        looking = false
    }

    /// Paste whatever is on the clipboard, the way the keyboard's "use copied client" works.
    func lookUpPasteboard() async {
        guard let s = UIPasteboard.general.string, !s.isEmpty else {
            lookupNote = "Copy their name or number first."
            return
        }
        await look(up: s)
    }
}

struct DeskView: View {
    @StateObject private var model: DeskModel
    @State private var tab = Tab.pieces

    enum Tab: Hashable { case templates, pieces, draft, book }

    init(insert: @escaping (String) -> Void, collapse: @escaping () -> Void) {
        _model = StateObject(wrappedValue: DeskModel(insert: insert, collapse: collapse))
    }

    var body: some View {
        VStack(spacing: 0) {
            ClientBar(model: model)
            Divider()
            TabView(selection: $tab) {
                PiecesTab(model: model)
                    .tabItem { Label("Pieces", systemImage: "square.grid.2x2") }.tag(Tab.pieces)
                TemplatesTab(model: model)
                    .tabItem { Label("Templates", systemImage: "text.quote") }.tag(Tab.templates)
                DraftTab(model: model)
                    .tabItem { Label("Draft", systemImage: "sparkles") }.tag(Tab.draft)
                BookTab(model: model)
                    .tabItem { Label("Book", systemImage: "calendar") }.tag(Tab.book)
            }
            .tint(Ink.brand)
        }
    }
}

/// Who the message is for, across every tab. Naming a client personalises the notes, the drafts
/// and the selection link, and is what booking needs.
struct ClientBar: View {
    @ObservedObject var model: DeskModel
    @State private var typed = ""
    @State private var editing = false
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                if model.hasClient && !editing {
                    Image(systemName: "person.crop.circle.fill").foregroundStyle(Ink.brand)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(model.name.isEmpty ? (model.ref?.value ?? "") : model.name)
                            .font(.subheadline.weight(.semibold))
                        if let n = model.cartCount, n > 0 {
                            Text("\(n) in an open basket").font(.caption).foregroundStyle(Ink.soft)
                        }
                    }
                    Spacer()
                    if model.looking { ProgressView().controlSize(.small) }
                    Button("Change") { editing = true; typed = ""; focused = true }
                        .font(.footnote).foregroundStyle(Ink.soft)
                } else {
                    TextField("Who is this for?", text: $typed)
                        .textFieldStyle(.roundedBorder)
                        .focused($focused)
                        .autocorrectionDisabled()
                        .onSubmit { Task { await find() } }
                    Button {
                        Task { await model.lookUpPasteboard(); editing = false }
                    } label: { Image(systemName: "doc.on.clipboard") }
                        .font(.footnote).foregroundStyle(Ink.soft)
                    Button("Find") { Task { await find() } }
                        .font(.footnote.weight(.semibold)).foregroundStyle(Ink.brand)
                        .disabled(typed.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            if let note = model.lookupNote {
                HStack {
                    Text(note).font(.caption).foregroundStyle(Ink.soft)
                    Spacer()
                }
            }
            if let url = model.cartURL, model.hasClient, !editing {
                Button {
                    model.send(url)
                } label: {
                    Label("Send their basket back", systemImage: "bag")
                        .font(.footnote.weight(.semibold))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .foregroundStyle(Ink.deep)
            }
        }
        .padding(.horizontal, 14).padding(.top, 12).padding(.bottom, 10)
    }

    private func find() async {
        let q = typed.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        await model.look(up: q)
        editing = false
    }
}

// MARK: - Small shared pieces

/// A dropdown that reads as a pill rather than a form control.
struct FilterPill: View {
    let text: String
    var body: some View {
        HStack(spacing: 3) {
            Text(text).lineLimit(1)
            Image(systemName: "chevron.down").font(.system(size: 9, weight: .semibold))
        }
        .font(.footnote)
        .foregroundStyle(Ink.deep)
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.secondary.opacity(0.12)))
    }
}

/// The one action at the foot of a tab.
struct SendBar: View {
    let title: String
    let enabled: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title)
                .fontWeight(.semibold)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: 12)
                    .fill(enabled ? Ink.brand : Color.secondary.opacity(0.3)))
                .foregroundColor(.white)
        }
        .disabled(!enabled)
        .padding(12)
    }
}

/// What a tab says when it needs a client and has not been given one.
struct NeedsClient: View {
    let what: String
    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "person.crop.circle.badge.questionmark")
                .font(.system(size: 26)).foregroundStyle(Ink.soft)
            Text("Name the client above to \(what).")
                .font(.footnote).foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, 30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
