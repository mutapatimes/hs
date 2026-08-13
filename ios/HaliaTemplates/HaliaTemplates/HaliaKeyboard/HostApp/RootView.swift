// Target membership: HOST APP ONLY.
//
// The app you download: a quiet, luxury welcome, then an elevated setup where you connect and enter
// your store info. Deliberately not the stock iOS Settings look: paper ground, the system serif
// (New York) for display, one green accent, gold hairlines.
import SwiftUI

@MainActor
final class RootModel: ObservableObject {
    @Published var token: String
    @Published var baseURL: String
    @Published var templates: [Template]
    @Published var info: [String: String] = [:]   // store-info snippets, by label
    @Published var status: String = ""
    @Published var isError: Bool = false
    @Published var busy: Bool = false

    init() {
        token = Credentials.token
        baseURL = Credentials.baseURL
        templates = TemplateStore.load()
        var m: [String: String] = [:]
        for label in StoreInfoStore.labels { m[label] = StoreInfoStore.value(for: label) }
        info = m
        if let at = TemplateStore.syncedAt, !templates.isEmpty {
            let f = RelativeDateTimeFormatter()
            status = "\(templates.count) templates, synced \(f.localizedString(for: at, relativeTo: Date()))."
        }
    }

    func sync() async {
        let t = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else {
            status = "Paste your Halia token first."; isError = true; return
        }
        busy = true; isError = false; status = "Syncing…"
        Credentials.token = t
        Credentials.baseURL = baseURL
        do {
            let fetched = try await HaliaAPI(baseURL: baseURL, token: t).fetchTemplates()
            TemplateStore.save(fetched)
            templates = fetched
            await CallDirectory.refresh()   // also refresh the VIP caller-ID list for the Call Directory ext
            if fetched.isEmpty {
                status = "Connected. No templates in Halia yet."; isError = true
            } else {
                status = "\(fetched.count) templates ✓"; isError = false
            }
        } catch {
            status = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            isError = true
        }
        busy = false
    }

    func saveInfo() {
        for label in StoreInfoStore.labels { StoreInfoStore.set(info[label] ?? "", for: label) }
    }
}

// MARK: - Palette + shared pieces

private enum Palette {
    static let ink       = Color(red: 0.106, green: 0.114, blue: 0.133)
    static let soft      = Color(red: 0.373, green: 0.388, blue: 0.420)
    static let faint     = Color(red: 0.604, green: 0.576, blue: 0.522)
    static let brand     = Color(red: 0.122, green: 0.337, blue: 0.290)
    static let brandDeep = Color(red: 0.078, green: 0.227, blue: 0.196)
    static let gold      = Color(red: 0.651, green: 0.486, blue: 0.204)
    static let card      = Color(red: 0.988, green: 0.984, blue: 0.969)
    static let line      = Color(red: 0.902, green: 0.882, blue: 0.835)
    static let bgTop     = Color(red: 0.980, green: 0.973, blue: 0.949)
    static let bg        = Color(red: 0.957, green: 0.945, blue: 0.918)
    static let bg2       = Color(red: 0.918, green: 0.898, blue: 0.851)
}

private func serif(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
    .system(size: size, weight: weight, design: .serif)
}

private let mark = "\u{2042}"   // ⁂ the Halia asterism

private struct PaperBackground: View {
    var body: some View {
        LinearGradient(colors: [Palette.bgTop, Palette.bg, Palette.bg2],
                       startPoint: .top, endPoint: .bottom)
            .ignoresSafeArea()
    }
}

private struct Card<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding(20)
            .background(RoundedRectangle(cornerRadius: 20).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(Palette.line, lineWidth: 1))
            .shadow(color: Color.black.opacity(0.08), radius: 20, x: 0, y: 12)
    }
}

private func cardLabel(_ text: String) -> some View {
    Text(text.uppercased()).font(serif(12.5)).foregroundColor(Palette.gold)
}

private struct LuxeField: View {
    let label: String
    @Binding var text: String
    var secure = false
    var keyboard: UIKeyboardType = .default
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label.uppercased()).font(.system(size: 11.5, weight: .semibold)).foregroundColor(Palette.faint)
            Group {
                if secure { SecureField("", text: $text) } else { TextField("", text: $text) }
            }
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .keyboardType(keyboard)
            .font(.system(size: 15))
            .foregroundColor(Palette.ink)
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.white))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.line, lineWidth: 1))
        }
    }
}

private struct LuxeButton: View {
    let title: String
    let action: () -> Void
    init(_ title: String, action: @escaping () -> Void) { self.title = title; self.action = action }
    var body: some View {
        Button(action: action) {
            Text(title).font(.system(size: 15, weight: .semibold)).foregroundColor(.white)
                .padding(.horizontal, 20).padding(.vertical, 13)
                .background(RoundedRectangle(cornerRadius: 13).fill(Palette.brand))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Root

struct RootView: View {
    @StateObject private var model = RootModel()
    @State private var showSetup = Credentials.hasToken   // returning users skip the welcome

    var body: some View {
        ZStack {
            PaperBackground()
            if showSetup {
                SetupView(model: model)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            } else {
                WelcomeView { withAnimation(.easeInOut(duration: 0.45)) { showSetup = true } }
                    .transition(.opacity)
            }
        }
        .onOpenURL { handleURL($0) }
    }

    /// Route halia:// deep links: connect = the dashboard QR, today = the widget's tap.
    private func handleURL(_ url: URL) {
        guard url.scheme == "halia" else { return }
        switch url.host {
        case "connect":
            handleConnect(url)
        case "today":
            // The Reach-today widget opened us. There is no in-app client browser yet, so just come
            // forward to the connected view; the queue lives in the widget and the dashboard for now.
            withAnimation(.easeInOut(duration: 0.35)) { showSetup = true }
        default:
            break
        }
    }

    /// Handle halia://connect?t=<token>&b=<base> from the dashboard QR: store the credentials and
    /// sync, so the merchant never types a token.
    private func handleConnect(_ url: URL) {
        guard url.scheme == "halia", url.host == "connect",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
        else { return }
        let token = items.first { $0.name == "t" }?.value ?? ""
        let base = items.first { $0.name == "b" }?.value ?? ""
        guard !token.isEmpty else { return }
        model.token = token
        if !base.isEmpty { model.baseURL = base }
        Credentials.token = token
        if !base.isEmpty { Credentials.baseURL = base }
        withAnimation(.easeInOut(duration: 0.35)) { showSetup = true }
        Task { await model.sync() }
    }
}

// MARK: - Welcome

private struct WelcomeView: View {
    let onBegin: () -> Void
    var body: some View {
        ZStack {
            PaperBackground()
            Text(mark).font(serif(300)).foregroundColor(Palette.gold).opacity(0.05)
                .offset(x: 120, y: -260)
            VStack(spacing: 0) {
                Spacer()
                Text(mark).font(serif(30)).foregroundColor(Palette.brand)
                Text("Halia").font(serif(74)).foregroundColor(Palette.ink).padding(.top, 18)
                RoundedRectangle(cornerRadius: 1).fill(Palette.gold).frame(width: 46, height: 2).padding(.vertical, 26)
                Text("Private client care, in your pocket.")
                    .font(serif(22)).foregroundColor(Palette.brandDeep)
                    .multilineTextAlignment(.center)
                Text("Your templates, your clients and your house voice, one tap away inside WhatsApp.")
                    .font(.system(size: 15)).foregroundColor(Palette.soft)
                    .multilineTextAlignment(.center).padding(.top, 14).padding(.horizontal, 44)
                Spacer()
                VStack(spacing: 16) {
                    Button(action: onBegin) {
                        Text("Begin").font(.system(size: 17, weight: .semibold)).foregroundColor(.white)
                            .frame(maxWidth: .infinity).padding(.vertical, 17)
                            .background(RoundedRectangle(cornerRadius: 16).fill(Palette.brand))
                    }
                    .buttonStyle(.plain)
                    Button(action: onBegin) {
                        (Text("Already set up?  ").foregroundColor(Palette.soft)
                         + Text("Connect").foregroundColor(Palette.brand).bold())
                            .font(.system(size: 14))
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 34).padding(.bottom, 44)
            }
        }
    }
}

// MARK: - Setup

private struct SetupView: View {
    @ObservedObject var model: RootModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(mark).font(serif(20)).foregroundColor(Palette.brand)
                    Text("Set up your desk").font(serif(34)).foregroundColor(Palette.ink)
                    Text("A few quiet minutes, once.").font(.system(size: 14.5)).foregroundColor(Palette.soft)
                }
                .padding(.top, 8).padding(.bottom, 2)

                Card {
                    cardLabel("Connect")
                    Text("Open Halia on your computer, go to Settings, and scan the QR with your phone. Or paste a token below.")
                        .font(.system(size: 13)).foregroundColor(Palette.soft).lineSpacing(2)
                    LuxeField(label: "Halia token", text: $model.token, secure: true)
                    LuxeField(label: "Address", text: $model.baseURL, keyboard: .URL)
                    HStack(spacing: 12) {
                        LuxeButton(model.busy ? "Syncing…" : "Connect & sync") { Task { await model.sync() } }
                            .disabled(model.busy)
                        if !model.status.isEmpty {
                            Text(model.status).font(.system(size: 13.5, weight: .semibold))
                                .foregroundColor(model.isError ? .red : Palette.brand)
                        }
                    }
                    .padding(.top, 4)
                }

                Card {
                    cardLabel("What your house offers")
                    ForEach(StoreInfoStore.labels, id: \.self) { label in
                        LuxeField(label: label, text: Binding(
                            get: { model.info[label] ?? "" },
                            set: { model.info[label] = $0 }))
                    }
                    LuxeButton("Save") { model.saveInfo() }.padding(.top, 4)
                }
                Text("These appear in the keyboard under a “Store info” category, one tap to insert.")
                    .font(.system(size: 12.5)).foregroundColor(Palette.faint).padding(.horizontal, 4)

                Card {
                    cardLabel("Turn on the keyboard")
                    Text("Settings › General › Keyboard › Keyboards › add Halia, then allow Full Access.")
                        .font(.system(size: 14)).foregroundColor(Palette.soft).lineSpacing(2)
                    Text("In WhatsApp, tap the globe to switch to Halia. To personalise, copy the client's name in the chat, then tap Use copied client.")
                        .font(.system(size: 14)).foregroundColor(Palette.soft).lineSpacing(2)
                }
            }
            .padding(.horizontal, 22).padding(.bottom, 44)
        }
        .background(PaperBackground())
    }
}

#Preview {
    RootView()
}
