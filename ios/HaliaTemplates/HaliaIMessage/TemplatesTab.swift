// Target membership: HaliaIMessage ONLY.
//
// The house templates, synced from Halia. The keyboard shows these as a scrolling row of pills;
// here there is room to read one before sending it, which is the difference between picking a
// template and choosing the right one.
import SwiftUI

struct TemplatesTab: View {
    @ObservedObject var model: DeskModel
    @State private var templates: [Template] = []
    @State private var category: String?
    @State private var query = ""
    @State private var preview: Template?
    @State private var greeting = true
    @State private var signoff = true

    private var categories: [String] {
        var seen = Set<String>()
        return templates.map { $0.category }.filter { seen.insert($0).inserted }.sorted()
    }

    /// What Halia ranked for this client, first and labelled, then the rest.
    private var suggested: [Template] {
        guard !model.suggested.isEmpty else { return [] }
        let wanted = Set(model.suggested)
        return templates.filter { wanted.contains($0.name) }
    }

    private var listed: [Template] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        return templates.filter { t in
            (category == nil || t.category == category)
                && (q.isEmpty || t.name.lowercased().contains(q) || t.body.lowercased().contains(q))
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            if templates.isEmpty {
                VStack(spacing: 6) {
                    Text("No templates synced yet.").font(.footnote).foregroundStyle(.secondary)
                    Text("Open the Halia app and tap Sync now.")
                        .font(.caption).foregroundStyle(Ink.soft)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                HStack(spacing: 8) {
                    TextField("Search your templates", text: $query)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                    Menu {
                        Button("All") { category = nil }
                        ForEach(categories, id: \.self) { c in Button(c) { category = c } }
                    } label: { FilterPill(text: category ?? "All") }
                }
                .padding(.horizontal, 12).padding(.vertical, 8)

                List {
                    if !suggested.isEmpty && query.isEmpty && category == nil {
                        Section("For \(model.firstName.isEmpty ? "this client" : model.firstName)") {
                            ForEach(suggested) { row($0) }
                        }
                    }
                    Section {
                        ForEach(listed) { row($0) }
                    }
                }
                .listStyle(.plain)
            }
        }
        .task { templates = TemplateStore.load() }
        .sheet(item: $preview) { t in
            NavigationStack {
                ScrollView {
                    Text(t.ready(firstName: model.firstName.isEmpty ? nil : model.firstName,
                                 greeting: greeting, signoff: signoff))
                        .font(.callout)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                }
                .safeAreaInset(edge: .bottom) {
                    VStack(spacing: 0) {
                        HStack(spacing: 16) {
                            Toggle("Greeting", isOn: $greeting)
                            Toggle("Sign-off", isOn: $signoff)
                        }
                        .toggleStyle(.switch).tint(Ink.brand)
                        .font(.footnote)
                        .padding(.horizontal, 14).padding(.top, 8)
                        SendBar(title: "Put it in the chat", enabled: true) {
                            model.send(t.ready(firstName: model.firstName.isEmpty ? nil : model.firstName,
                                               greeting: greeting, signoff: signoff))
                            preview = nil
                        }
                    }
                    .background(.bar)
                }
                .navigationTitle(t.name)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Back") { preview = nil } }
                }
            }
        }
    }

    private func row(_ t: Template) -> some View {
        Button { preview = t } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text(t.name).font(.subheadline.weight(.semibold)).foregroundStyle(.primary)
                Text(t.ready(firstName: model.firstName.isEmpty ? nil : model.firstName))
                    .font(.footnote).foregroundStyle(.secondary).lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
