// Target membership: HOST APP ONLY.
//
// The app you download: a full-bleed image welcome, then an elevated step-by-step setup that mirrors
// the site's connect flow, and a calm "ready" home once you are connected. Deliberately not the stock
// iOS Settings look: paper ground, the system serif (New York) for display, one green accent, green
// depth for emphasis (no gold).
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
    @Published var signedIn: Bool = Credentials.hasToken
    @Published var seatName: String = Credentials.name

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
            let (fetched, seat) = try await HaliaAPI(baseURL: baseURL, token: t).fetchContext()
            TemplateStore.save(fetched)
            templates = fetched
            Credentials.name = seat ?? ""
            seatName = Credentials.name
            signedIn = true
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

    /// Sign this device out: tell Halia the seat is inactive, then wipe every on-device credential
    /// and cache. The keyboard reads these, so it falls back to its "connect in the app" state.
    func signOut() async {
        await HaliaAPI.current.signout()
        Credentials.clear()
        TemplateStore.save([])
        SavedItemsStore.clear()
        DirectoryStore.clear()
        AppGroup.defaults.removeObject(forKey: "halia.recentTemplateIds")
        await CallDirectory.refresh()          // no token now → clears the caller-ID list too
        token = ""
        baseURL = Credentials.baseURL
        templates = []
        seatName = ""
        signedIn = false
        status = "Signed out."
        isError = false
    }
}

// MARK: - Palette + shared pieces

private enum Palette {
    static let ink       = Color(red: 0.106, green: 0.114, blue: 0.133)
    static let soft      = Color(red: 0.373, green: 0.388, blue: 0.420)
    static let faint     = Color(red: 0.560, green: 0.575, blue: 0.560)
    static let brand     = Color(red: 0.122, green: 0.337, blue: 0.290)
    static let brandDeep = Color(red: 0.055, green: 0.180, blue: 0.153)
    static let sage      = Color(red: 0.365, green: 0.475, blue: 0.435)   // muted green for labels (replaces gold)
    static let card      = Color(red: 0.988, green: 0.984, blue: 0.969)
    static let line      = Color(red: 0.894, green: 0.886, blue: 0.859)
    static let bgTop     = Color(red: 0.980, green: 0.973, blue: 0.949)
    static let bg        = Color(red: 0.957, green: 0.945, blue: 0.918)
    static let bg2       = Color(red: 0.918, green: 0.902, blue: 0.867)
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
            .shadow(color: Color.black.opacity(0.07), radius: 20, x: 0, y: 12)
    }
}

private func cardLabel(_ text: String) -> some View {
    Text(text.uppercased()).font(serif(12.5)).foregroundColor(Palette.sage).kerning(0.8)
}

private struct LuxeField: View {
    let label: String
    @Binding var text: String
    var secure = false
    var keyboard: UIKeyboardType = .default
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label.uppercased()).font(.system(size: 11.5, weight: .semibold)).foregroundColor(Palette.faint).kerning(0.4)
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

private enum Phase { case splash, wizard, home }

struct RootView: View {
    @StateObject private var model = RootModel()
    @State private var phase: Phase = Credentials.hasToken ? .home : .splash
    @State private var startStep = 0

    var body: some View {
        ZStack {
            PaperBackground()
            switch phase {
            case .splash:
                WelcomeView { go(.wizard) }
                    .transition(.opacity)
            case .wizard:
                WizardView(model: model, startStep: startStep) { withAnimation(.easeInOut(duration: 0.4)) { phase = .home } }
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            case .home:
                HomeView(model: model,
                         onEditInfo: { startStep = 1; go(.wizard) },
                         onReconnect: { startStep = 0; go(.wizard) })
                    .transition(.opacity)
            }
        }
        .onOpenURL { handleURL($0) }
    }

    private func go(_ p: Phase) {
        withAnimation(.easeInOut(duration: 0.45)) { phase = p }
    }

    /// Route halia:// deep links: connect = the dashboard QR, today = the widget's tap.
    private func handleURL(_ url: URL) {
        guard url.scheme == "halia" else { return }
        switch url.host {
        case "connect": handleConnect(url)
        case "today":   go(model.signedIn ? .home : .wizard)
        default:        break
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
        startStep = 0
        go(.wizard)
        Task { await model.sync() }
    }
}

// MARK: - Welcome (image splash)

private struct WelcomeView: View {
    let onBegin: () -> Void
    @State private var appear = false

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .bottom) {
                Image("SplashClient")
                    .resizable()
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height)
                    .clipped()

                // Deep-green scrim: legible white type at the base, image breathes up top.
                LinearGradient(
                    stops: [
                        .init(color: Palette.brandDeep.opacity(0.00), location: 0.0),
                        .init(color: Palette.brandDeep.opacity(0.22), location: 0.42),
                        .init(color: Palette.brandDeep.opacity(0.72), location: 0.70),
                        .init(color: Palette.brandDeep.opacity(0.96), location: 1.0),
                    ],
                    startPoint: .top, endPoint: .bottom)

                VStack(alignment: .leading, spacing: 0) {
                    Text(mark).font(serif(26)).foregroundColor(.white.opacity(0.9))
                    Text("Halia")
                        .font(serif(64)).foregroundColor(.white)
                        .padding(.top, 10)
                    RoundedRectangle(cornerRadius: 1).fill(.white.opacity(0.55))
                        .frame(width: 44, height: 1.5).padding(.vertical, 20)
                    Text("Private client care, in your pocket.")
                        .font(serif(23)).foregroundColor(.white)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Your templates, your clients and your house voice, one tap away inside WhatsApp.")
                        .font(.system(size: 15)).foregroundColor(.white.opacity(0.82))
                        .lineSpacing(3).padding(.top, 12)
                        .fixedSize(horizontal: false, vertical: true)

                    Button(action: onBegin) {
                        Text("Begin").font(.system(size: 17, weight: .semibold)).foregroundColor(Palette.brandDeep)
                            .frame(maxWidth: .infinity).padding(.vertical, 17)
                            .background(RoundedRectangle(cornerRadius: 16).fill(.white))
                    }
                    .buttonStyle(.plain).padding(.top, 30)

                    Button(action: onBegin) {
                        (Text("Already set up?  ").foregroundColor(.white.opacity(0.75))
                         + Text("Connect").foregroundColor(.white).bold())
                            .font(.system(size: 14))
                    }
                    .buttonStyle(.plain)
                    .frame(maxWidth: .infinity).padding(.top, 16)
                }
                .padding(.horizontal, 30).padding(.bottom, 48)
                .offset(y: appear ? 0 : 22)
                .opacity(appear ? 1 : 0)
            }
            .ignoresSafeArea()
        }
        .onAppear {
            withAnimation(.easeOut(duration: 0.7).delay(0.05)) { appear = true }
        }
    }
}

// MARK: - Wizard

private struct WizardView: View {
    @ObservedObject var model: RootModel
    let startStep: Int
    let onFinish: () -> Void

    @State private var step: Int
    private let total = 3

    init(model: RootModel, startStep: Int, onFinish: @escaping () -> Void) {
        self.model = model
        self.startStep = startStep
        self.onFinish = onFinish
        _step = State(initialValue: startStep)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            TabView(selection: $step) {
                ConnectStep(model: model).tag(0)
                StoreInfoStep(model: model).tag(1)
                KeyboardStep().tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .animation(.easeInOut(duration: 0.35), value: step)

            navBar
        }
        .background(PaperBackground())
    }

    private var header: some View {
        VStack(spacing: 14) {
            Text(mark).font(serif(20)).foregroundColor(Palette.brand)
            HStack(spacing: 6) {
                ForEach(0..<total, id: \.self) { i in
                    Capsule()
                        .fill(i <= step ? Palette.brand : Palette.line)
                        .frame(height: 3)
                        .animation(.easeInOut(duration: 0.3), value: step)
                }
            }
            .padding(.horizontal, 60)
            Text("Step \(step + 1) of \(total)")
                .font(.system(size: 12, weight: .medium)).foregroundColor(Palette.faint).kerning(0.4)
        }
        .padding(.top, 16).padding(.bottom, 8)
    }

    private var navBar: some View {
        HStack {
            if step > 0 {
                Button(action: back) {
                    Text("Back").font(.system(size: 15, weight: .semibold)).foregroundColor(Palette.soft)
                        .padding(.horizontal, 18).padding(.vertical, 13)
                }
                .buttonStyle(.plain)
            }
            Spacer()
            Button(action: next) {
                Text(step == total - 1 ? "Enter your desk" : "Continue")
                    .font(.system(size: 15, weight: .semibold)).foregroundColor(.white)
                    .padding(.horizontal, 24).padding(.vertical, 14)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Palette.brand))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 22).padding(.vertical, 12)
        .background(
            Palette.bgTop.opacity(0.96)
                .overlay(Rectangle().fill(Palette.line).frame(height: 1), alignment: .top)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    private func back() {
        withAnimation(.easeInOut(duration: 0.35)) { step = max(0, step - 1) }
    }

    private func next() {
        if step == 1 { model.saveInfo() }          // persist store info as you leave that step
        if step == total - 1 { onFinish(); return }
        withAnimation(.easeInOut(duration: 0.35)) { step = min(total - 1, step + 1) }
    }
}

private struct StepScaffold<Content: View>: View {
    let title: String
    let subtitle: String
    let content: Content
    init(_ title: String, _ subtitle: String, @ViewBuilder content: () -> Content) {
        self.title = title; self.subtitle = subtitle; self.content = content()
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(title).font(serif(32)).foregroundColor(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(subtitle).font(.system(size: 14.5)).foregroundColor(Palette.soft)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.top, 6)
                content
            }
            .padding(.horizontal, 22).padding(.bottom, 28)
        }
    }
}

private struct ConnectStep: View {
    @ObservedObject var model: RootModel
    var body: some View {
        StepScaffold("Connect Halia", "Scan the code from your dashboard, or paste a token.") {
            Card {
                cardLabel("Connect")
                Text("Open Halia on your computer, go to Settings, and scan the QR with your phone. Or paste a token below.")
                    .font(.system(size: 13)).foregroundColor(Palette.soft).lineSpacing(2)
                LuxeField(label: "Halia token", text: $model.token, secure: true)
                LuxeField(label: "Address", text: $model.baseURL, keyboard: .URL)
                HStack(spacing: 12) {
                    LuxeButton("Connect & sync") { Task { await model.sync() } }
                        .disabled(model.busy)
                        .opacity(model.busy ? 0.5 : 1)
                    if model.busy {
                        HaliaLoadingRow(label: "Syncing")
                    } else if !model.status.isEmpty {
                        Text(model.status).font(.system(size: 13.5, weight: .semibold))
                            .foregroundColor(model.isError ? .red : Palette.brand)
                    }
                }
                .padding(.top, 4)
                if model.signedIn {
                    HStack {
                        Text(model.seatName.isEmpty ? "Signed in" : "Signed in as \(model.seatName)")
                            .font(.system(size: 13)).foregroundColor(Palette.soft)
                        Spacer()
                        Button("Sign out") { Task { await model.signOut() } }
                            .font(.system(size: 13, weight: .semibold)).foregroundColor(.red)
                    }
                    .padding(.top, 2)
                }
            }
        }
    }
}

private struct StoreInfoStep: View {
    @ObservedObject var model: RootModel
    var body: some View {
        StepScaffold("What your house offers", "These appear in the keyboard under Store info, one tap to insert.") {
            Card {
                cardLabel("Your house")
                ForEach(StoreInfoStore.labels, id: \.self) { label in
                    LuxeField(label: label, text: Binding(
                        get: { model.info[label] ?? "" },
                        set: { model.info[label] = $0 }))
                }
            }
            Text("You can change these any time from your desk.")
                .font(.system(size: 12.5)).foregroundColor(Palette.faint).padding(.horizontal, 4)
        }
    }
}

private struct KeyboardStep: View {
    private let steps = [
        "Open Settings › General › Keyboard › Keyboards, add Halia, then allow Full Access.",
        "In WhatsApp, tap the globe to switch to Halia.",
        "To personalise, copy the client's name in the chat, then tap Use copied client.",
    ]
    var body: some View {
        StepScaffold("Turn on the keyboard", "Three short steps, and Halia lives inside every chat.") {
            Card {
                cardLabel("Turn on the keyboard")
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { i, s in
                        HStack(alignment: .top, spacing: 12) {
                            Text("\(i + 1)")
                                .font(serif(15, .semibold)).foregroundColor(.white)
                                .frame(width: 26, height: 26)
                                .background(Circle().fill(Palette.brand))
                            Text(s).font(.system(size: 14.5)).foregroundColor(Palette.soft).lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Home (connected)

private struct HomeView: View {
    @ObservedObject var model: RootModel
    let onEditInfo: () -> Void
    let onReconnect: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(mark).font(serif(22)).foregroundColor(Palette.brand)
                    Text("Your desk is ready").font(serif(34)).foregroundColor(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(model.seatName.isEmpty ? "Signed in." : "Signed in as \(model.seatName).")
                        .font(.system(size: 14.5)).foregroundColor(Palette.soft)
                }
                .padding(.top, 12)

                Card {
                    cardLabel("Synced")
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("\(model.templates.count)").font(serif(40)).foregroundColor(Palette.brand)
                        Text(model.templates.count == 1 ? "template" : "templates")
                            .font(.system(size: 15)).foregroundColor(Palette.soft)
                    }
                    if !model.status.isEmpty {
                        Text(model.status).font(.system(size: 13)).foregroundColor(model.isError ? .red : Palette.faint)
                    }
                    HStack(spacing: 12) {
                        LuxeButton(model.busy ? "Syncing…" : "Resync") { Task { await model.sync() } }
                            .disabled(model.busy).opacity(model.busy ? 0.5 : 1)
                        if model.busy { HaliaLoadingRow(label: "Syncing") }
                    }
                    .padding(.top, 4)
                }

                Card {
                    cardLabel("Manage")
                    homeRow("Store info", "What your house offers", action: onEditInfo)
                    Divider().overlay(Palette.line)
                    homeRow("Reconnect", "Scan a new code or paste a token", action: onReconnect)
                    Divider().overlay(Palette.line)
                    Button(action: { Task { await model.signOut() } }) {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Sign out").font(.system(size: 15, weight: .semibold)).foregroundColor(.red)
                                Text("Clears this device").font(.system(size: 12.5)).foregroundColor(Palette.faint)
                            }
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 22).padding(.bottom, 44)
        }
        .background(PaperBackground())
    }

    private func homeRow(_ title: String, _ sub: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.system(size: 15, weight: .semibold)).foregroundColor(Palette.ink)
                    Text(sub).font(.system(size: 12.5)).foregroundColor(Palette.faint)
                }
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundColor(Palette.faint)
            }
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    RootView()
}
