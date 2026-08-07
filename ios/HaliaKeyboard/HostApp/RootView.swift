// Target membership: HOST APP ONLY.
//
// One screen: connect with your Halia token, sync templates into the App Group, optionally set a
// client first name, and a short guide to turning the keyboard on. That is the whole host app.
import SwiftUI

@MainActor
final class RootModel: ObservableObject {
    @Published var token: String
    @Published var baseURL: String
    @Published var templates: [Template]
    @Published var status: String = ""
    @Published var isError: Bool = false
    @Published var busy: Bool = false

    init() {
        token = Credentials.token
        baseURL = Credentials.baseURL
        templates = TemplateStore.load()
        if let at = TemplateStore.syncedAt, !templates.isEmpty {
            let f = RelativeDateTimeFormatter()
            status = "\(templates.count) templates, synced \(f.localizedString(for: at, relativeTo: Date()))."
        }
    }

    func sync() async {
        let t = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else {
            status = "Paste your Halia extension token first."; isError = true; return
        }
        busy = true; isError = false; status = "Syncing…"
        Credentials.token = t
        Credentials.baseURL = baseURL

        do {
            let fetched = try await HaliaAPI(baseURL: baseURL, token: t).fetchTemplates()
            TemplateStore.save(fetched)
            templates = fetched
            if fetched.isEmpty {
                status = "Connected, but Halia has no templates yet. Add some in Halia, Settings."
                isError = true
            } else {
                status = "Synced \(fetched.count) templates."
                isError = false
            }
        } catch {
            status = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            isError = true
        }
        busy = false
    }
}

struct RootView: View {
    @StateObject private var model = RootModel()

    private let brand = Color(red: 0.12, green: 0.34, blue: 0.29) // #1F564A

    var body: some View {
        NavigationView {
            Form {
                Section("Connect to Halia") {
                    SecureField("Halia extension token", text: $model.token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Halia address", text: $model.baseURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Button {
                        Task { await model.sync() }
                    } label: {
                        HStack {
                            Text(model.busy ? "Syncing…" : "Connect and sync templates")
                            if model.busy { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(model.busy)
                    if !model.status.isEmpty {
                        Text(model.status)
                            .font(.footnote)
                            .foregroundStyle(model.isError ? Color.red : brand)
                    }
                }

                if !model.templates.isEmpty {
                    Section("Your templates (\(model.templates.count))") {
                        ForEach(model.templates) { t in
                            VStack(alignment: .leading, spacing: 3) {
                                Text(t.name).font(.subheadline).bold()
                                Text(t.category).font(.caption).foregroundStyle(.secondary)
                                Text(t.preview).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }

                Section {
                    Label("Settings, General, Keyboard, Keyboards, Add New Keyboard, choose Halia.",
                          systemImage: "1.circle")
                        .font(.footnote)
                    Label("Open Halia in that list and turn on Allow Full Access.",
                          systemImage: "2.circle")
                        .font(.footnote)
                    Label("In WhatsApp, tap the globe to switch to Halia. To personalise, copy the client's name or number in the chat, then tap Use copied client.",
                          systemImage: "3.circle")
                        .font(.footnote)
                } header: {
                    Text("Turn on the Halia keyboard")
                } footer: {
                    Text("Full Access lets the keyboard read what you copy and reach your Halia account, so it can draft a personal message and fill the client's name. Halia acts only on what you copy and tap.")
                }
            }
            .navigationTitle("Halia Templates")
        }
        .navigationViewStyle(.stack)
    }
}

#Preview {
    RootView()
}
