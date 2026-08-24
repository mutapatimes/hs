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

    /// Connect from a scanned code (a halia://connect?t=…&b=… payload) or a pasted token, then sync.
    /// The address is fixed to the default unless the code carries its own, so nobody types a URL.
    func connect(scanned raw: String) {
        var t = "", b = ""
        if let comps = URLComponents(string: raw), comps.scheme == "halia" {
            t = comps.queryItems?.first { $0.name == "t" }?.value ?? ""
            b = comps.queryItems?.first { $0.name == "b" }?.value ?? ""
        } else {
            t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard !t.isEmpty else { status = "That code did not contain a Halia token."; isError = true; return }
        token = t
        if !b.isEmpty { baseURL = b }
        Task { await sync() }
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

    var body: some View {
        ZStack {
            PaperBackground()
            switch phase {
            case .splash:
                WelcomeView { go(.wizard) }
                    .transition(.opacity)
            case .wizard:
                WizardView(model: model, onBack: { go(.splash) },
                           onFinish: { withAnimation(.easeInOut(duration: 0.4)) { phase = .home } })
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            case .home:
                HomeView(model: model, onReconnect: { go(.wizard) }, onSignedOut: { go(.splash) })
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

    /// Handle halia://connect?t=<token>&b=<base> from the dashboard QR opened in the system camera:
    /// route to the wizard and connect, so the merchant never types a token.
    private func handleConnect(_ url: URL) {
        guard url.host == "connect" else { return }
        go(.wizard)
        model.connect(scanned: url.absoluteString)
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
        }
        .ignoresSafeArea()
        .onAppear {
            withAnimation(.easeOut(duration: 0.7).delay(0.05)) { appear = true }
        }
    }
}

// MARK: - Wizard

private struct WizardView: View {
    @ObservedObject var model: RootModel
    let onBack: () -> Void
    let onFinish: () -> Void

    @State private var step = 0
    private let total = 3

    var body: some View {
        VStack(spacing: 0) {
            header
            TabView(selection: $step) {
                ConnectStep(model: model).tag(0)
                KeyboardStep().tag(1)
                ExtensionsStep().tag(2)
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
            // Always reachable, even on the first step — backing out of step 0 leaves the wizard
            // entirely rather than doing nothing, so there is never a screen with no way out.
            Button(action: back) {
                Text("Back").font(.system(size: 15, weight: .semibold)).foregroundColor(Palette.soft)
                    .padding(.horizontal, 18).padding(.vertical, 13)
            }
            .buttonStyle(.plain)
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
        if step > 0 {
            withAnimation(.easeInOut(duration: 0.35)) { step -= 1 }
        } else {
            onBack()
        }
    }

    private func next() {
        if step == total - 1 {
            guard model.signedIn else {
                // Nothing connected yet — "Enter your desk" would just be an empty desk. Send them
                // back to Connect instead of finishing into a screen with nothing on it.
                withAnimation(.easeInOut(duration: 0.35)) { step = 0 }
                model.status = "Connect first, then you're in."
                model.isError = true
                return
            }
            onFinish(); return
        }
        withAnimation(.easeInOut(duration: 0.35)) { step = min(total - 1, step + 1) }
    }
}

private struct StepScaffold<Content: View>: View {
    let title: String
    let subtitle: String
    let content: Content
    init(_ title: String, _ subtitle: String = "", @ViewBuilder content: () -> Content) {
        self.title = title; self.subtitle = subtitle; self.content = content()
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(title).font(serif(32)).foregroundColor(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    if !subtitle.isEmpty {
                        Text(subtitle).font(.system(size: 14.5)).foregroundColor(Palette.soft)
                            .fixedSize(horizontal: false, vertical: true)
                    }
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
    @State private var showScanner = false
    @State private var showToken = false

    var body: some View {
        StepScaffold("Connect Halia") {
            Card {
                Text("Open Settings in Halia on your computer, then scan the code shown there.")
                    .font(.system(size: 13.5)).foregroundColor(Palette.soft).lineSpacing(2)

                Button { showScanner = true } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "qrcode.viewfinder").font(.system(size: 18, weight: .semibold))
                        Text("Scan QR code").font(.system(size: 15, weight: .semibold))
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity).padding(.vertical, 14)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Palette.brand))
                }
                .buttonStyle(.plain).padding(.top, 2)

                if model.busy {
                    HaliaLoadingRow(label: "Syncing").padding(.top, 2)
                } else if !model.status.isEmpty {
                    Text(model.status).font(.system(size: 13.5, weight: .semibold))
                        .foregroundColor(model.isError ? .red : Palette.brand).padding(.top, 2)
                }

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

                Divider().overlay(Palette.line).padding(.vertical, 2)
                if showToken {
                    LuxeField(label: "Halia token", text: $model.token, secure: true)
                    LuxeButton("Connect & sync") { model.connect(scanned: model.token) }
                        .disabled(model.busy).opacity(model.busy ? 0.5 : 1)
                } else {
                    Button("Paste a token instead") { withAnimation { showToken = true } }
                        .font(.system(size: 13, weight: .semibold)).foregroundColor(Palette.sage)
                }
            }
        }
        .fullScreenCover(isPresented: $showScanner) {
            QRScanner(
                onCode: { code in showScanner = false; model.connect(scanned: code) },
                onCancel: { showScanner = false })
        }
    }
}

private struct KeyboardStep: View {
    var body: some View {
        StepScaffold("Turn on the keyboard") {
            Card {
                Text("Add Halia under Keyboards, then allow Full Access.")
                    .font(.system(size: 13.5)).foregroundColor(Palette.soft).lineSpacing(2)

                Button(action: openSettings) {
                    HStack(spacing: 10) {
                        Image(systemName: "gearshape.fill").font(.system(size: 16, weight: .semibold))
                        Text("Open Settings").font(.system(size: 15, weight: .semibold))
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity).padding(.vertical, 14)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Palette.brand))
                }
                .buttonStyle(.plain).padding(.top, 2)

                Text("Then in WhatsApp, tap the globe key to switch to Halia.")
                    .font(.system(size: 13.5)).foregroundColor(Palette.soft).lineSpacing(2).padding(.top, 2)
            }
        }
    }
}

/// Deep link to the Settings app. Apple gives no way to land on a specific pane (Keyboards, Call
/// Blocking & Identification), so this opens Settings' root and the copy names where to go next.
private func openSettings() {
    guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
    UIApplication.shared.open(url)
}

private struct FeatureRow: View {
    let icon: String
    let title: String
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon).font(.system(size: 15, weight: .semibold)).foregroundColor(.white)
                .frame(width: 32, height: 32)
                .background(Circle().fill(Palette.brand))
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 14.5, weight: .semibold)).foregroundColor(Palette.ink)
                Text(text).font(.system(size: 13.5)).foregroundColor(Palette.soft).lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct ExtensionsStep: View {
    var body: some View {
        StepScaffold("Two more tools") {
            Card {
                FeatureRow(icon: "square.and.arrow.up", title: "Share to a client",
                    text: "Share a product or a page into Halia, and send it straight to the right client.")
                Divider().overlay(Palette.line)
                FeatureRow(icon: "phone.fill", title: "Know who's calling",
                    text: "A client's name and grade show up when they call, not just a number.")
            }
            Button(action: openSettings) {
                HStack(spacing: 10) {
                    Image(systemName: "gearshape.fill").font(.system(size: 16, weight: .semibold))
                    Text("Turn on caller ID").font(.system(size: 15, weight: .semibold))
                }
                .foregroundColor(.white)
                .frame(maxWidth: .infinity).padding(.vertical, 14)
                .background(RoundedRectangle(cornerRadius: 14).fill(Palette.brand))
            }
            .buttonStyle(.plain)
            Text("Settings › Phone › Call Blocking & Identification.")
                .font(.system(size: 12.5)).foregroundColor(Palette.faint)
        }
    }
}

// MARK: - Home (connected)

private struct HomeView: View {
    @ObservedObject var model: RootModel
    let onReconnect: () -> Void
    let onSignedOut: () -> Void
    @State private var showOpeners = false

    private var syncLine: String {
        if model.busy { return "Syncing your templates…" }
        if model.isError, !model.status.isEmpty { return model.status }
        let n = model.templates.count
        return n == 0 ? "No templates yet" : "\(n) template\(n == 1 ? "" : "s") ready"
    }

    // The desk has genuinely nothing to report yet: not mid-sync, not erroring, just empty. The
    // masthead gets a living field instead of a flat gradient here, so waiting doesn't feel inert.
    private var isEmptyDesk: Bool { !model.busy && !model.isError && model.templates.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            masthead
            VStack(spacing: 0) {
                row("Message openers", "The angles you send from Share") { showOpeners = true }
                hairline
                row("Reconnect", "Scan a new code or paste a token", action: onReconnect)
                hairline
                row(model.busy ? "Syncing…" : "Sync now", "Refresh your templates and clients") {
                    Task { await model.sync() }
                }
            }
            .padding(.horizontal, 24).padding(.top, 6)

            Spacer(minLength: 24)
            Button(action: { Task { await model.signOut(); onSignedOut() } }) {
                Text("Sign out").font(.system(size: 14, weight: .semibold)).foregroundColor(Palette.soft)
            }
            .buttonStyle(.plain).padding(.horizontal, 24).padding(.bottom, 24)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(PaperBackground())
        .ignoresSafeArea(edges: .top)
        .sheet(isPresented: $showOpeners) { OpenersEditor() }
    }

    // A deep-green masthead that anchors the screen and reads like a private-client desk, not a
    // settings pane. The asterism stays small and letterspaced here, where it reads as a mark.
    private var masthead: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("\(mark)  HALIA")
                .font(.system(size: 12.5, weight: .semibold)).kerning(3)
                .foregroundColor(.white.opacity(0.65))
            Text("Your desk").font(serif(44)).foregroundColor(.white)
            HStack(spacing: 8) {
                Circle().fill(model.isError ? Color(red: 0.90, green: 0.68, blue: 0.42)
                                             : Color(red: 0.56, green: 0.80, blue: 0.63))
                    .frame(width: 7, height: 7)
                Text(syncLine).font(.system(size: 14)).foregroundColor(.white.opacity(0.85))
                if model.busy { ProgressView().tint(.white).scaleEffect(0.7) }
            }
            .padding(.top, 2)
            if !model.seatName.isEmpty {
                Text("Signed in as \(model.seatName)")
                    .font(.system(size: 13)).foregroundColor(.white.opacity(0.5))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 24)
        .padding(.top, 76)
        .padding(.bottom, 32)
        .background {
            if isEmptyDesk {
                LivingGradient()
            } else {
                LinearGradient(colors: [Palette.brandDeep, Palette.brand],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
            }
        }
    }

    private var hairline: some View { Rectangle().fill(Palette.line).frame(height: 1) }

    private func row(_ title: String, _ sub: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.system(size: 16, weight: .medium)).foregroundColor(Palette.ink)
                    Text(sub).font(.system(size: 12.5)).foregroundColor(Palette.faint)
                }
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundColor(Palette.faint)
            }
            .padding(.vertical, 16)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// A slow-breathing mesh of the house greens for the empty "no templates yet" desk. The four corners
// stay anchored in the same two tones the ordinary masthead uses, so the white type above keeps its
// contrast; three interior points drift and shift between brand and sage, each on its own long,
// unsynchronised cycle, so it reads as alive rather than a moving wallpaper.
private struct LivingGradient: View {
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: false)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            MeshGradient(
                width: 3, height: 3,
                points: [
                    SIMD2(0, 0),                                  SIMD2(0.5, 0),                                SIMD2(1, 0),
                    drift(0, 0.5, t, period: 19, seed: 0),        drift(0.5, 0.5, t, period: 23, seed: 7),      drift(1, 0.5, t, period: 17, seed: 3),
                    SIMD2(0, 1),                                  SIMD2(0.5, 1),                                SIMD2(1, 1),
                ],
                colors: [
                    Palette.brandDeep, Palette.brand,                    Palette.brandDeep,
                    glow(t, period: 14, seed: 1), glow(t, period: 18, seed: 5), glow(t, period: 12, seed: 9),
                    Palette.brandDeep, Palette.brand,                    Palette.brandDeep,
                ]
            )
        }
    }

    private func drift(_ x: Double, _ y: Double, _ t: Double, period: Double, seed: Double) -> SIMD2<Float> {
        let a = (t / period + seed) * 2 * .pi
        return SIMD2(Float(x + 0.07 * sin(a)), Float(y + 0.05 * cos(a * 0.8)))
    }

    private let brandRGB: (Double, Double, Double) = (0.122, 0.337, 0.290)
    private let sageRGB: (Double, Double, Double) = (0.365, 0.475, 0.435)

    private func glow(_ t: Double, period: Double, seed: Double) -> Color {
        let m = (sin((t / period + seed) * 2 * .pi) + 1) / 2   // eases 0...1...0, never snaps
        return Color(red: brandRGB.0 + (sageRGB.0 - brandRGB.0) * m,
                     green: brandRGB.1 + (sageRGB.1 - brandRGB.1) * m,
                     blue: brandRGB.2 + (sageRGB.2 - brandRGB.2) * m)
    }
}

// MARK: - Openers editor

/// Edit the message openers the Share extension offers when you share a page and pick a client. One
/// set per page kind (product, collection, care, returns…). Saved to the App Group; Share reads them
/// straight away.
private struct OpenersEditor: View {
    @Environment(\.dismiss) private var dismiss
    @State private var sets: [PageKind: [Opener]] = OpenersEditor.initialSets()

    private static func initialSets() -> [PageKind: [Opener]] {
        Dictionary(uniqueKeysWithValues: PageKind.allCases.map { ($0, OpenersStore.load($0)) })
    }

    var body: some View {
        NavigationView {
            List {
                Text("These appear as chips when you share a page into Halia and pick a client. The client's name and the link are added for you. Write {title} where the product's name should go.")
                    .font(.system(size: 12.5)).foregroundColor(Palette.faint)
                    .listRowBackground(Color.clear)
                ForEach(PageKind.allCases) { kind in
                    Section(header: Text(kind.title)) {
                        ForEach(binding(for: kind)) { $o in
                            VStack(alignment: .leading, spacing: 6) {
                                TextField("Name", text: $o.label)
                                    .font(.system(size: 13, weight: .semibold)).foregroundColor(Palette.brand)
                                TextField("Message", text: $o.body, axis: .vertical)
                                    .font(.system(size: 15))
                            }
                            .padding(.vertical, 4)
                        }
                        .onDelete { sets[kind]?.remove(atOffsets: $0) }
                        Button {
                            sets[kind, default: []].append(Opener(label: "New opener", body: ""))
                        } label: {
                            Label("Add opener", systemImage: "plus.circle")
                        }
                        .tint(Palette.brand)
                    }
                }
            }
            .navigationTitle("Message openers")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Reset all") { for k in PageKind.allCases { sets[k] = OpenersStore.defaults[k] ?? [] } }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        for k in PageKind.allCases { OpenersStore.save(sets[k] ?? [], for: k) }
                        dismiss()
                    }
                    .fontWeight(.semibold)
                }
            }
        }
    }

    private func binding(for kind: PageKind) -> Binding<[Opener]> {
        Binding(get: { sets[kind] ?? [] }, set: { sets[kind] = $0 })
    }
}

#Preview {
    RootView()
}
