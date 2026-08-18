// Target membership: HaliaShare (the Share extension) ONLY.
//
// The card shown when you share a client into Halia: who they are, their grade, why they surfaced,
// their open basket, and the next actions that matter. Draft a reply, write a basket nudge, or send
// a lookbook; then copy it or send it straight to WhatsApp or Messages, and log it to the pipeline.
// Reuses the keyboard's HaliaAPI. Nothing is stored.
import SwiftUI
import UIKit

struct ShareRootView: View {
    let query: String
    let onOpen: (URL) -> Void        // open a wa.me / sms: link (best effort from an extension)
    let onClose: () -> Void

    @State private var phase: Phase = .loading
    @State private var result: HaliaAPI.LookupResult?
    @State private var draft = ""
    @State private var busy = false
    @State private var busyKind = ""      // which action is running: reply / nudge / look
    @State private var status = ""
    @State private var copied = false
    @State private var contacted = false
    @State private var pickingTemplate = false

    // Reverse flow: when a product URL is shared, pick which client to send it to.
    @State private var mode: Mode = .client
    @State private var clients: [HaliaAPI.Client] = []
    @State private var search = ""
    @State private var chosen: HaliaAPI.Client?
    @State private var productLink = ""
    @State private var activeOpener = ""
    @State private var openers: [Opener] = OpenersStore.load()   // editable in the host app

    enum Mode { case client, product }
    enum Phase { case loading, found, notfound, signedOut, error(String) }

    private let green = Color(red: 0.12, green: 0.34, blue: 0.29)

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    switch phase {
                    case .loading:    loading
                    case .signedOut:  stateView("link", "Connect Halia first", "Open Halia and connect your store, then try again.")
                    case .notfound:   stateView("magnifyingglass", "No Halia signal", "“\(query)” is not a flagged client in your book yet.")
                    case .error(let e): stateView("exclamationmark.triangle", "Something went wrong", e)
                    case .found:      foundView
                    }
                }
                .padding(18)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 6) {
                        Text("⁂").foregroundColor(green).font(.system(size: 15, weight: .bold))
                        Text("Halia").font(.system(size: 16, weight: .semibold))
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done", action: onClose)
                }
            }
        }
        .task { await run() }
        .sheet(isPresented: $pickingTemplate) {
            TemplatePicker(firstName: result?.name) { text in
                draft = text; copied = false; pickingTemplate = false
            }
        }
    }

    // MARK: states

    private var loading: some View {
        VStack(spacing: 12) {
            ProgressView()
            Text(mode == .product ? "Opening your client book…" : "Looking up \(query)…")
                .font(.system(size: 14)).foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 30)
    }

    @ViewBuilder private var foundView: some View {
        if mode == .product { productView } else { found }
    }

    private func stateView(_ symbol: String, _ title: String, _ subtitle: String? = nil) -> some View {
        VStack(spacing: 10) {
            Image(systemName: symbol).font(.system(size: 30)).foregroundColor(green.opacity(0.7))
            Text(title).font(.system(size: 18, weight: .semibold)).multilineTextAlignment(.center)
            if let subtitle {
                Text(subtitle).font(.system(size: 14)).foregroundColor(.secondary).multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity).padding(.vertical, 30)
    }

    private var found: some View {
        let r = result
        return VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                if let g = r?.grade, !g.isEmpty {
                    Text(g)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(.white)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(gradeColor(g))
                }
                Text(r?.name ?? query).font(.system(size: 20, weight: .semibold))
                Spacer()
            }
            if let latent = r?.latent, !latent.isEmpty {
                Text("\(latent) latent value").font(.system(size: 13)).foregroundColor(.secondary)
            }
            if let action = r?.action, !action.isEmpty {
                Text(action).font(.system(size: 14, weight: .medium)).foregroundColor(green)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let cart = r?.cart, let count = cart.count, count > 0 {
                Text("Open basket · \(count) item\(count == 1 ? "" : "s")")
                    .font(.system(size: 13, weight: .medium)).foregroundColor(green)
            }
            if let reasons = r?.reasons, !reasons.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("WHY THIS CLIENT SURFACED")
                        .font(.system(size: 10, weight: .semibold)).foregroundColor(.secondary).kerning(0.5)
                    ForEach(reasons.prefix(4), id: \.self) { why in
                        HStack(alignment: .top, spacing: 8) {
                            Text("·").foregroundColor(green).bold()
                            Text(why).font(.system(size: 13)).foregroundColor(.primary)
                        }
                    }
                }
            }

            Divider()
            if draft.isEmpty { composeButtons } else { draftBlock }
            if !status.isEmpty {
                Text(status).font(.system(size: 12.5)).foregroundColor(.secondary)
            }

            if let cid = r?.cid, !cid.isEmpty {
                Button(action: { Task { await markContacted() } }) {
                    Text(contacted ? "Logged to pipeline ✓" : "Mark contacted")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(contacted ? .secondary : green)
                }
                .disabled(contacted)
            }
        }
    }

    // MARK: compose

    private var composeButtons: some View {
        VStack(spacing: 10) {
            actionButton(busyKind == "reply" ? "Drafting…" : "Draft a reply", filled: true) {
                Task { await makeDraft() }
            }
            if let cart = result?.cart, (cart.count ?? 0) > 0, !(cart.url ?? "").isEmpty {
                actionButton(busyKind == "nudge" ? "Writing…" : "Nudge basket", filled: false) {
                    Task { await makeNudge() }
                }
            }
            actionButton(busyKind == "look" ? "Curating…" : "Send a lookbook", filled: false) {
                Task { await makeLookbook() }
            }
            actionButton("Choose a template", filled: false) { pickingTemplate = true }
        }
        .disabled(busy)
        .opacity(busy ? 0.6 : 1)
    }

    private var draftBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextEditor(text: $draft)
                .font(.system(size: 14))
                .foregroundColor(.primary)
                .scrollContentBackground(.hidden)
                .frame(minHeight: 120, maxHeight: 260)
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color(.separator), lineWidth: 0.5))
                .onChange(of: draft) { _, _ in copied = false }   // edited text is no longer the copied text
            Text("Tap to edit before you send.")
                .font(.system(size: 11.5)).foregroundColor(.secondary)
            HStack(spacing: 10) {
                sendButton(copied ? "Copied ✓" : "Copy", system: "doc.on.doc") { copyDraft() }
                if rawNumber != nil {
                    sendButton("WhatsApp", system: "message.fill") { send(.whatsapp) }
                    sendButton("Messages", system: "bubble.left.fill") { send(.messages) }
                }
            }
            Button("Start over") { draft = ""; copied = false }
                .font(.system(size: 13)).foregroundColor(.secondary)
        }
    }

    private func actionButton(_ title: String, filled: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(filled ? .white : green)
                .frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(filled ? green : .clear)
                        .overlay(RoundedRectangle(cornerRadius: 12)
                            .stroke(green.opacity(filled ? 0 : 0.4), lineWidth: 1))
                )
        }
        .buttonStyle(.plain)
    }

    private func sendButton(_ title: String, system: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: system).font(.system(size: 13, weight: .semibold))
                Text(title).font(.system(size: 14, weight: .semibold))
            }
            .foregroundColor(green)
            .frame(maxWidth: .infinity).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 10).fill(green.opacity(0.10)))
        }
        .buttonStyle(.plain)
    }

    // MARK: send

    private enum Channel { case whatsapp, messages }

    /// A number to send to: the chosen client (reverse flow) or the matched client's phone from the
    /// lookup, else the shared value when a phone was what you shared.
    private var rawNumber: String? {
        let candidate = (mode == .product ? chosen?.phone : result?.phone)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let p = candidate, !p.isEmpty {
            let cleaned = p.filter { $0.isNumber || $0 == "+" }
            if cleaned.filter(\.isNumber).count >= 6 { return cleaned }
        }
        if mode == .client, let ref = ClientClassifier.classify(query), ref.kind == .phone { return ref.value }
        return nil
    }

    private func send(_ ch: Channel) {
        UIPasteboard.general.string = draft            // always leave the text, in case open is blocked
        guard let raw = rawNumber else { return }
        let text = draft.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let url: URL? = {
            switch ch {
            case .whatsapp: return URL(string: "https://wa.me/\(raw.filter { $0.isNumber })?text=\(text)")
            case .messages: return URL(string: "sms:\(raw)&body=\(text)")
            }
        }()
        if let url { onOpen(url) }
        Task { await markContacted() }                 // a send is a real contact
    }

    // MARK: actions

    private func run() async {
        guard Credentials.hasToken else { phase = .signedOut; return }
        if Self.isProductURL(query) {          // shared a product -> reverse flow: pick a client
            mode = .product
            await loadClients()
            return
        }
        guard let ref = ClientClassifier.classify(query) else { phase = .notfound; return }
        phase = .loading
        do {
            let r = try await HaliaAPI.current.lookup(ref)
            result = r
            phase = (r.found == true) ? .found : .notfound
        } catch {
            phase = .error((error as? HaliaAPIError)?.errorDescription ?? "Could not reach Halia.")
        }
    }

    private static func isProductURL(_ s: String) -> Bool {
        s.contains("://") && s.contains("/products/")
    }

    private func loadClients() async {
        phase = .loading
        do {
            clients = try await HaliaAPI.current.clients()
            phase = .found
        } catch {
            phase = .error((error as? HaliaAPIError)?.errorDescription ?? "Could not reach Halia.")
        }
    }

    /// A client was chosen for the shared product: turn the product URL into a catalogue link and
    /// pre-write a note. The draft is editable and the send buttons use the client's number.
    private func choose(_ c: HaliaAPI.Client) async {
        chosen = c; copied = false; status = ""; productLink = ""
        busy = true; defer { busy = false }
        do {
            let r = try await HaliaAPI.current.catalogueFromUrls(urls: [query], name: c.name)
            if r.url.isEmpty { status = "Could not build a link for this product." }
            else if let first = openers.first { productLink = r.url; applyOpener(first) }
            else { productLink = r.url; draft = productLink }
        } catch {
            status = "Could not build a link for this product."
        }
    }

    private func applyOpener(_ o: Opener) {
        activeOpener = o.label
        let first = chosen?.name.split(separator: " ").first.map(String.init) ?? ""
        var msg = first.isEmpty ? o.body : "\(first),\n\n\(o.body)"
        if !productLink.isEmpty { msg += "\n\n" + productLink }
        draft = msg; copied = false
    }

    private func makeDraft() async {
        guard let ref = ClientClassifier.classify(query) else { return }
        busy = true; busyKind = "reply"; status = ""
        defer { busy = false; busyKind = "" }
        if let d = try? await HaliaAPI.current.draft(ref, channel: "message", instruction: "Reply warmly and personally.") {
            draft = d.draft ?? ""
        } else { status = "Could not draft a message." }
    }

    private func makeNudge() async {
        guard let ref = ClientClassifier.classify(query), let url = result?.cart?.url, !url.isEmpty else { return }
        busy = true; busyKind = "nudge"; status = ""
        defer { busy = false; busyKind = "" }
        if let d = try? await HaliaAPI.current.draft(ref, channel: "message",
            instruction: "They have items in their basket they have not checked out. Write a warm, personal note offering to help them complete it or answer any questions.") {
            draft = (d.draft ?? "") + "\n\n" + url
        } else { status = "Could not write a basket nudge." }
    }

    private func makeLookbook() async {
        guard let ref = ClientClassifier.classify(query) else { return }
        busy = true; busyKind = "look"; status = ""
        defer { busy = false; busyKind = "" }
        do {
            let picks = try await HaliaAPI.current.suggest(ref, instruction: "")
            let ids = picks.map { $0.productId }
            guard !ids.isEmpty else { status = "No pieces to suggest just now."; return }
            let link = try await HaliaAPI.current.catalogue(productIds: ids, name: result?.name ?? "")
            draft = "I set aside a few pieces I thought you would love. You can see them here:\n\(link)"
        } catch {
            status = "Could not build a lookbook."
        }
    }

    private func copyDraft() {
        UIPasteboard.general.string = draft
        copied = true
    }

    private func markContacted() async {
        let cid = (mode == .product ? chosen?.cid : result?.cid)
        let name = (mode == .product ? chosen?.name : result?.name)
        guard let cid, !cid.isEmpty, !contacted else { return }
        _ = try? await HaliaAPI.current.logContacted(cid: cid, clientName: name, reason: "Contacted from Share")
        contacted = true
    }

    // MARK: product (reverse) flow

    private var filteredClients: [HaliaAPI.Client] {
        let q = search.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return q.isEmpty ? clients : clients.filter { $0.name.lowercased().contains(q) }
    }

    @ViewBuilder private var productView: some View {
        if let c = chosen {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 10) {
                    gradeBadge(c.grade)
                    Text(c.name).font(.system(size: 20, weight: .semibold))
                    Spacer()
                    Button("Change") { chosen = nil; draft = ""; copied = false }
                        .font(.system(size: 14, weight: .medium)).foregroundColor(green)
                }
                if busy {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Preparing the link…").font(.system(size: 14)).foregroundColor(.secondary)
                    }
                } else if !productLink.isEmpty {
                    Text("OPENER").font(.system(size: 10, weight: .semibold)).foregroundColor(.secondary).kerning(0.5)
                    openerChips
                    draftBlock
                }
                if !status.isEmpty { Text(status).font(.system(size: 12.5)).foregroundColor(.secondary) }
                if let cid = c.cid, !cid.isEmpty {
                    Button(action: { Task { await markContacted() } }) {
                        Text(contacted ? "Logged to pipeline ✓" : "Mark contacted")
                            .font(.system(size: 14, weight: .medium)).foregroundColor(contacted ? .secondary : green)
                    }
                    .disabled(contacted)
                }
            }
        } else {
            VStack(alignment: .leading, spacing: 14) {
                Text("Send this piece").font(.system(size: 22, weight: .semibold))
                Text("Pick a client from your book.").font(.system(size: 14)).foregroundColor(.secondary)
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundColor(.secondary).font(.system(size: 14))
                    TextField("Search clients", text: $search).textInputAutocapitalization(.words)
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))

                if clients.isEmpty {
                    Text("No clients in your book yet. Sync in the Halia app.")
                        .font(.system(size: 14)).foregroundColor(.secondary).padding(.top, 8)
                } else {
                    LazyVStack(spacing: 0) {
                        ForEach(filteredClients) { c in
                            Button { Task { await choose(c) } } label: { clientRow(c) }
                                .buttonStyle(.plain)
                            Divider()
                        }
                    }
                }
            }
        }
    }

    private var openerChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(openers) { o in
                    Button { applyOpener(o) } label: {
                        Text(o.label)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundColor(o.label == activeOpener ? .white : green)
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(Capsule().fill(o.label == activeOpener ? green : green.opacity(0.10)))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 1)
        }
    }

    private func clientRow(_ c: HaliaAPI.Client) -> some View {
        HStack(spacing: 10) {
            gradeBadge(c.grade)
            VStack(alignment: .leading, spacing: 2) {
                Text(c.name).font(.system(size: 15, weight: .semibold)).foregroundColor(.primary)
                if let l = c.latent, !l.isEmpty {
                    Text("\(l) latent value").font(.system(size: 12)).foregroundColor(.secondary)
                }
            }
            Spacer()
            Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundColor(.secondary)
        }
        .contentShape(Rectangle())
        .padding(.vertical, 10)
    }

    @ViewBuilder private func gradeBadge(_ g: String) -> some View {
        if !g.isEmpty {
            Text(g).font(.system(size: 12, weight: .bold)).foregroundColor(.white)
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(gradeColor(g))
        }
    }

    // Brand grade colours (no gold): A* charcoal, A green, B slate, else grey.
    private func gradeColor(_ g: String) -> Color {
        switch g.uppercased() {
        case "A*": return Color(red: 0.10, green: 0.11, blue: 0.13)
        case "A":  return green
        case "B":  return Color(red: 0.37, green: 0.42, blue: 0.45)
        default:   return Color(red: 0.55, green: 0.56, blue: 0.59)
        }
    }
}

/// The synced templates, grouped by category, for the share card. Tapping one fills {first_name}
/// with the looked-up client's name and hands the ready text back as the draft to copy or send.
private struct TemplatePicker: View {
    let firstName: String?
    let onPick: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var templates: [Template] = TemplateStore.load()
    // Shares the keyboard's stored preference, so "Dear"/"Sign-off" stay consistent across surfaces.
    @State private var greeting = (AppGroup.defaults.object(forKey: "halia.kb.greeting") as? Bool) ?? true
    @State private var signoff  = (AppGroup.defaults.object(forKey: "halia.kb.signoff") as? Bool) ?? true

    private let green = Color(red: 0.12, green: 0.34, blue: 0.29)

    private var grouped: [(String, [Template])] {
        let cats = Array(Set(templates.map { $0.category })).sorted()
        return cats.map { cat in (cat, templates.filter { $0.category == cat }) }
    }

    var body: some View {
        NavigationView {
            Group {
                if templates.isEmpty {
                    VStack(spacing: 8) {
                        Text("No templates yet").font(.system(size: 17, weight: .semibold))
                        Text("Open Halia and connect your store to sync your templates.")
                            .font(.system(size: 14)).foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .padding(40).frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List {
                        Section {
                            Toggle("Include greeting", isOn: $greeting)
                            Toggle("Include sign-off", isOn: $signoff)
                        }
                        .tint(green)
                        ForEach(grouped, id: \.0) { cat, items in
                            Section(header: Text(cat)) {
                                ForEach(items) { t in
                                    Button { onPick(t.ready(firstName: firstName, greeting: greeting, signoff: signoff)) } label: {
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(t.name).font(.system(size: 15, weight: .semibold)).foregroundColor(.primary)
                                            Text(t.preview).font(.system(size: 12.5)).foregroundColor(.secondary).lineLimit(2)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Templates")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
        .onChange(of: greeting) { _, v in AppGroup.defaults.set(v, forKey: "halia.kb.greeting") }
        .onChange(of: signoff)  { _, v in AppGroup.defaults.set(v, forKey: "halia.kb.signoff") }
    }
}
