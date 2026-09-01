// Target membership: HaliaIMessage ONLY.
//
// Pick from what the associate saved while browsing, or from the range narrowed to what suits this
// client, then send it as a selection they can tap through, or as a basket they can pay.
//
// What goes into the conversation is the plain link, not a Halia message bubble: a bubble would
// offer the App Store to anyone without the app, and no client installs a boutique's app. The link
// carries preview tags, so it arrives as an image card.
import SwiftUI

struct PiecesTab: View {
    @ObservedObject var model: DeskModel

    @State private var query = ""
    @State private var results: [HaliaAPI.Product] = []
    @State private var saved: [SavedItemsStore.Item] = []
    @State private var chosen: Set<String> = []
    @State private var busy = false
    @State private var status: String?
    // The view being browsed: a collection and a size, and the ids of everything they match, so a
    // whole shelf can go into one selection without ticking it piece by piece.
    @State private var collection = ""
    @State private var size = ""
    @State private var viewIds: [String] = []
    @State private var collections: [String] = []
    @State private var sizes: [String] = []

    /// The whole shelf, with anything saved while browsing pinned above it. A search narrows the
    /// products; the saved pieces stay put so they are never a search away.
    private var savedRows: [(id: String, title: String, image: String?)] {
        query.trimmingCharacters(in: .whitespaces).isEmpty
            ? saved.map { (id: $0.url, title: $0.title ?? $0.url, image: nil) } : []
    }
    private var productRows: [(id: String, title: String, image: String?)] {
        results.map { (id: $0.id, title: $0.title, image: $0.image) }
    }
    private var rows: [(id: String, title: String, image: String?)] { savedRows + productRows }
    private var savedIds: Set<String> { Set(savedRows.map { $0.id }) }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TextField("Search your products", text: $query)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .onSubmit { Task { await search() } }
                Button("Search") { Task { await search() } }.font(.footnote.weight(.semibold))
            }
            .padding(.horizontal, 12).padding(.top, 10)

            filterRow.padding(.horizontal, 12).padding(.vertical, 8)

            if rows.isEmpty && busy {
                Spacer(); ProgressView(); Spacer()
            } else if rows.isEmpty {
                Spacer()
                Text(status ?? "No products came back. This needs a store with published, in-stock products.")
                    .font(.footnote).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center).padding(.horizontal, 24)
                Spacer()
            } else {
                List(rows, id: \.id) { row in
                    Button {
                        if chosen.contains(row.id) { chosen.remove(row.id) } else { chosen.insert(row.id) }
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: chosen.contains(row.id) ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(chosen.contains(row.id) ? Ink.brand : Color.secondary)
                            if let img = row.image, let url = URL(string: img) {
                                AsyncImage(url: url) { image in
                                    image.resizable().aspectRatio(contentMode: .fill)
                                } placeholder: { Color.secondary.opacity(0.1) }
                                .frame(width: 38, height: 46).clipped()
                            }
                            Text(row.title).lineLimit(2)
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                }
                .listStyle(.plain)
                if let s = status {
                    HStack { Text(s).font(.caption).foregroundStyle(Ink.soft); Spacer() }
                        .padding(.horizontal, 14).padding(.top, 6)
                }
            }

            HStack(spacing: 10) {
                Button {
                    Task { await sendSelection() }
                } label: {
                    Text(busy ? "Sending…" : "Send selection (\(chosen.count))")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(RoundedRectangle(cornerRadius: 12)
                            .fill(chosen.isEmpty ? Color.secondary.opacity(0.3) : Ink.brand))
                        .foregroundColor(.white)
                }
                .disabled(chosen.isEmpty || busy)
                Button {
                    Task { await sendCart() }
                } label: {
                    Text("Pay in chat")
                        .fontWeight(.semibold)
                        .padding(.horizontal, 14).padding(.vertical, 12)
                        .background(RoundedRectangle(cornerRadius: 12)
                            .stroke(chosen.isEmpty ? Color.secondary.opacity(0.3) : Ink.brand, lineWidth: 1))
                        .foregroundStyle(chosen.isEmpty ? Color.secondary : Ink.brand)
                }
                .disabled(chosen.isEmpty || busy)
            }
            .padding(12)
        }
        .task {
            saved = SavedItemsStore.load()
            await search(initial: true)          // open on everything the store sells
        }
    }

    /// Narrow the range to what suits this client, then take the whole view at once.
    @ViewBuilder private var filterRow: some View {
        if !collections.isEmpty || !sizes.isEmpty {
            HStack(spacing: 8) {
                if !collections.isEmpty {
                    Menu {
                        Button("All collections") { collection = ""; Task { await search(initial: true) } }
                        ForEach(collections, id: \.self) { c in
                            Button(c) { collection = c; Task { await search(initial: true) } }
                        }
                    } label: { FilterPill(text: collection.isEmpty ? "All collections" : collection) }
                }
                if !sizes.isEmpty {
                    Menu {
                        Button("All sizes") { size = ""; Task { await search(initial: true) } }
                        ForEach(sizes, id: \.self) { s in
                            Button(s) { size = s; Task { await search(initial: true) } }
                        }
                    } label: { FilterPill(text: size.isEmpty ? "All sizes" : size) }
                }
                Spacer(minLength: 0)
                if !viewIds.isEmpty {
                    Button(chosen.count == viewIds.count ? "Clear" : "All \(viewIds.count)") {
                        if chosen.count == viewIds.count { chosen.removeAll() }
                        else { chosen = Set(viewIds) }
                    }
                    .font(.footnote.weight(.semibold)).foregroundStyle(Ink.brand)
                }
            }
        }
    }

    private func search(initial: Bool = false) async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard initial || !q.isEmpty else { return }
        busy = true; status = nil
        do {
            let view = try await HaliaAPI.current.searchProducts(q, limit: 100,
                                                                 collection: collection, size: size)
            results = view.products
            viewIds = view.ids
            if !view.collections.isEmpty { collections = view.collections }
            if !view.sizes.isEmpty { sizes = view.sizes }
            chosen.removeAll()
            if results.isEmpty {
                status = (collection.isEmpty && size.isEmpty && q.isEmpty)
                    ? "No products came back. This needs a store with published, in-stock products."
                    : "Nothing in this view."
            }
        } catch {
            status = (error as? LocalizedError)?.errorDescription ?? "Could not reach Halia."
        }
        busy = false
    }

    /// Product ids for what is ticked, resolving anything saved as a storefront link first.
    private func chosenIds() async throws -> [String] {
        let picked = rows.filter { chosen.contains($0.id) }.map { $0.id }
        let urls = picked.filter { savedIds.contains($0) }
        let ids = picked.filter { !savedIds.contains($0) }
        guard !urls.isEmpty else { return ids }
        let resolved = try await HaliaAPI.current.productsFromUrls(urls).products.map { $0.id }
        return resolved + ids
    }

    private func sendSelection() async {
        busy = true; status = nil
        do {
            let ids = try await chosenIds()
            let url = try await HaliaAPI.current.catalogue(
                productIds: ids, name: model.name.isEmpty ? nil : model.name,
                email: model.email, phone: model.phone)
            model.send(url)
        } catch {
            status = "Could not build that selection."
        }
        busy = false
    }

    private func sendCart() async {
        busy = true; status = nil
        do {
            let url = try await HaliaAPI.current.cartLink(productIds: try await chosenIds())
            model.send(url)
        } catch {
            status = "Nothing here has a buyable variant."
        }
        busy = false
    }
}
