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

// Matches the dashboard's Shopify-admin look: grey ground, white cards, admin greys, green accent.
private enum Palette {
    static let ink       = Color(red: 0.188, green: 0.188, blue: 0.188)   // #303030
    static let soft      = Color(red: 0.380, green: 0.380, blue: 0.380)   // #616161
    static let faint     = Color(red: 0.541, green: 0.541, blue: 0.541)   // #8A8A8A
    static let brand     = Color(red: 0.122, green: 0.337, blue: 0.290)
    static let brandDeep = Color(red: 0.055, green: 0.180, blue: 0.153)
    static let sage      = Color(red: 0.365, green: 0.475, blue: 0.435)   // muted green for labels
    static let card      = Color.white
    static let line      = Color(red: 0.890, green: 0.890, blue: 0.890)   // #E3E3E3
    static let bgTop     = Color(red: 0.945, green: 0.945, blue: 0.945)   // #F1F1F1
    static let bg        = Color(red: 0.945, green: 0.945, blue: 0.945)
    static let bg2       = Color(red: 0.945, green: 0.945, blue: 0.945)
}

// Display text follows the dashboard: the system sans, a step heavier than body.
private func serif(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
    .system(size: size, weight: weight == .regular ? .semibold : weight, design: .default)
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
            .background(RoundedRectangle(cornerRadius: 12).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.line, lineWidth: 1))
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
                .background(RoundedRectangle(cornerRadius: 12).fill(Palette.brand))
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
                            .background(RoundedRectangle(cornerRadius: 12).fill(.white))
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
    private let total = 4

    var body: some View {
        VStack(spacing: 0) {
            header
            TabView(selection: $step) {
                ConnectStep(model: model).tag(0)
                DetailsStep().tag(1)
                KeyboardStep().tag(2)
                ExtensionsStep().tag(3)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .animation(.easeInOut(duration: 0.35), value: step)

            navBar
        }
        .background(PaperBackground())
        .onAppear {
            // A fresh wizard never opens with yesterday's error on it; step-level messages
            // (a failed sync, the finish guard) still appear when they actually happen.
            if !model.signedIn { model.status = ""; model.isError = false }
        }
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
                    .background(RoundedRectangle(cornerRadius: 12).fill(Palette.brand))
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
                    .background(RoundedRectangle(cornerRadius: 12).fill(Palette.brand))
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

/// Who you are: signs every draft and template, and identifies your seat to the team.
private struct DetailsStep: View {
    @State private var card = MyCard.load()

    var body: some View {
        StepScaffold("Your details", "Your name and position sign every message Halia drafts for you.") {
            Card {
                LuxeField(label: "Your name", text: $card.name)
                LuxeField(label: "Work email", text: $card.email)
                LuxeField(label: "Position, e.g. Client Advisor", text: $card.title)
                LuxeField(label: "Sign-off (optional)", text: $card.signoff)
                Text("Leave the sign-off blank to sign with your name, position and the store.")
                    .font(.system(size: 12.5)).foregroundColor(Palette.faint)
            }
        }
        .task { await MyCard.prefillFromServer(); card = MyCard.load() }
        .onChange(of: card.name) { _ in card.save() }
        .onChange(of: card.email) { _ in card.save() }
        .onChange(of: card.title) { _ in card.save() }
        .onChange(of: card.signoff) { _ in card.save() }
        .onDisappear { card.syncToServer() }
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
                    .background(RoundedRectangle(cornerRadius: 12).fill(Palette.brand))
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
                .background(RoundedRectangle(cornerRadius: 12).fill(Palette.brand))
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
    @State private var showCapture = false
    @State private var showCaptureTools = false
    @State private var captureNote: String?
    @State private var captureId: String?
    @State private var followedUp = false
    @State private var birthdays: [HaliaAPI.Birthday] = []
    @State private var week: HaliaAPI.Week?
    @State private var weekDays = 365          // all by default; the picker narrows it
    @Environment(\.openURL) private var openURL

    private var syncLine: String {
        if model.busy { return "Syncing your templates…" }
        if model.isError, !model.status.isEmpty { return model.status }
        let n = model.templates.count
        return n == 0 ? "No templates yet" : "\(n) template\(n == 1 ? "" : "s") ready"
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 12) {
                        Image(systemName: model.isError ? "exclamationmark.circle.fill"
                                                        : "checkmark.seal.fill")
                            .font(.system(size: 30))
                            .foregroundStyle(model.isError ? Color.orange : Palette.brand)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(syncLine).font(.body.weight(.medium))
                            if !model.seatName.isEmpty {
                                Text("Signed in as \(model.seatName)")
                                    .font(.subheadline).foregroundStyle(.secondary)
                            }
                        }
                        Spacer()
                        if model.busy { ProgressView() }
                    }
                    .padding(.vertical, 4)
                }

                if let me = week?.me, week?.available == true {
                    Section {
                        Picker("Period", selection: $weekDays) {
                            Text("All").tag(365); Text("Month").tag(30); Text("Week").tag(7)
                        }
                        .pickerStyle(.segmented)
                        .onChange(of: weekDays) { _ in Task { week = try? await HaliaAPI.current.myWeek(days: weekDays) } }
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())],
                                  spacing: 14) {
                            weekStat("\(me.contacts ?? 0)", "contacts")
                            weekStat("\(me.captures ?? 0)", "captured")
                            weekStat("\(me.conversions ?? 0)", "converted")
                        }
                        .padding(.vertical, 6)
                        if (me.revenue ?? 0) > 0 || (me.contacts ?? 0) > 0 {
                            Text("£\(me.revenue ?? 0) from clients you contacted, "
                                 + "\(Int(((me.rate ?? 0) * 100).rounded()))% converted within two weeks.")
                                .font(.footnote).foregroundStyle(.secondary)
                        } else {
                            Text("Nothing logged yet. Contacts you log and clients you capture show here.")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    } header: { Text("Your results") }
                }

                if !birthdays.isEmpty {
                    Section {
                        ForEach(Array(birthdays.prefix(5).enumerated()), id: \.offset) { _, b in
                            HStack(spacing: 10) {
                                Image(systemName: "gift").foregroundStyle(Palette.brand)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(b.name ?? "A client").font(.body)
                                    Text(weekdayLine(b)).font(.footnote).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if let g = b.grade, !g.isEmpty {
                                    Text(g).font(.caption.weight(.semibold))
                                        .padding(.horizontal, 7).padding(.vertical, 3)
                                        .background(Capsule().fill(Palette.brand.opacity(0.12)))
                                        .foregroundStyle(Palette.brandDeep)
                                }
                            }
                        }
                    } header: { Text("Birthdays") } footer: {
                        Text("The birthday note is in your templates, ready to send.")
                    }
                }

                Section("Clients") {
                    navRow("Add a client", "Capture their details, straight into your book",
                           icon: "person.crop.circle.badge.plus", tint: Palette.brand) { showCapture = true }
                    navRow("Capture tools", "QR codes and your card, for the shop floor",
                           icon: "qrcode", tint: Palette.brandDeep) { showCaptureTools = true }
                }

                Section("Messaging") {
                    navRow("Message openers", "The angles you send from Share",
                           icon: "bubble.left.and.text.bubble.right.fill", tint: .indigo) { showOpeners = true }
                    navRow(model.busy ? "Syncing\u{2026}" : "Sync now",
                           "Refresh your templates and clients",
                           icon: "arrow.triangle.2.circlepath", tint: .teal) {
                        Task { await model.sync() }
                    }
                }

                Section {
                    navRow("Reconnect", "Scan a new code or paste a token",
                           icon: "qrcode.viewfinder", tint: .gray, action: onReconnect)
                    navRow("Support", "Live chat with us",
                           icon: "questionmark.circle.fill", tint: .blue) {
                        let base = Credentials.baseURL.hasSuffix("/")
                            ? String(Credentials.baseURL.dropLast()) : Credentials.baseURL
                        if let url = URL(string: base + "/contact?chat=open") { openURL(url) }
                    }
                }

                Section {
                    Button(role: .destructive) {
                        Task { await model.signOut(); onSignedOut() }
                    } label: {
                        Text("Sign out").frame(maxWidth: .infinity, alignment: .center)
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Halia")
            .tint(Palette.brand)
            .task { week = try? await HaliaAPI.current.myWeek(days: weekDays)
                    birthdays = (try? await HaliaAPI.current.birthdays()) ?? [] }
            .refreshable { await model.sync(); week = try? await HaliaAPI.current.myWeek(days: weekDays)
                           birthdays = (try? await HaliaAPI.current.birthdays()) ?? [] }
        }
        .sheet(isPresented: $showOpeners) { OpenersEditor() }
        .fullScreenCover(isPresented: $showCapture) {
            CaptureView { note, cid in captureNote = note; captureId = cid; followedUp = false }
        }
        .sheet(isPresented: $showCaptureTools) { CaptureToolsView() }
        .overlay(alignment: .bottom) {
            if let note = captureNote {
                HStack(spacing: 12) {
                    Text(note).font(.system(size: 13, weight: .semibold)).foregroundColor(.white)
                    if let cid = captureId, !followedUp {
                        Button {
                            followedUp = true
                            Task { try? await HaliaAPI.current.captureFollowUp(
                                customerId: cid, note: "Met in store, follow up today") }
                        } label: {
                            Text("Follow up today")
                                .font(.system(size: 13, weight: .semibold))
                                .padding(.horizontal, 10).padding(.vertical, 5)
                                .background(Capsule().fill(Color.white.opacity(0.18)))
                                .foregroundColor(.white)
                        }
                    } else if followedUp {
                        Text("On your list").font(.system(size: 12)).foregroundColor(.white.opacity(0.8))
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 10)
                .background(Capsule().fill(Palette.brandDeep))
                .padding(.bottom, 40)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .onAppear {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 8) {
                        withAnimation(.spring(duration: 0.4)) { captureNote = nil; captureId = nil }
                    }
                }
            }
        }
    }

    private func weekdayLine(_ b: HaliaAPI.Birthday) -> String {
        let n = b.in_days ?? 0
        let when = n == 0 ? "Today" : (n == 1 ? "Tomorrow" : "In \(n) days")
        return when + (b.date.map { " \u{00b7} " + String($0.suffix(5)).replacingOccurrences(of: "-", with: "/") } ?? "")
    }

    private func weekStat(_ value: String, _ label: String) -> some View {
        VStack(spacing: 3) {
            Text(value).font(.system(size: 24, weight: .semibold, design: .rounded))
                .foregroundStyle(.primary)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    /// A Settings-style row: tinted icon tile, title, subtitle, chevron via List.
    private func navRow(_ title: String, _ sub: String, icon: String, tint: Color,
                        action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 30, height: 30)
                    .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(tint))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(.primary)
                    Text(sub).font(.footnote).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
        }
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


// MARK: - Client capture (handover)
//
// The screen an associate hands to a client. Deliberately system-styled — a plain grouped form,
// like adding a contact — and store-voiced: the client is giving their details to the store
// (the data controller), and the profile's only home is the store's own Shopify. While it is
// open the rest of the app is unreachable; leaving it goes through a hand-back screen so the
// desk is never the first thing a client sees.
private struct CaptureView: View {
    let onDone: (String?, String?) -> Void      // (note for the toast, saved customer id)
    @Environment(\.dismiss) private var dismiss

    @State private var first = ""
    @State private var last = ""
    @State private var company = ""
    @State private var phone = ""
    @State private var email = ""
    @State private var birthday = ""
    @State private var address = ""
    @State private var postcode = ""
    @State private var city = ""
    @State private var country = ""
    @State private var sizes = ""
    @State private var preferences = ""
    @State private var notes = ""
    @State private var emailUpdates = false
    @State private var smsUpdates = false
    @State private var saving = false
    @State private var errorText: String?
    @State private var emailSuggestion: String?
    @State private var checkedOnce = false
    @State private var handBack = false     // saved (or cancelled): show the hand-back screen
    @State private var savedGrade: String?
    @State private var savedId: String?

    private var canSave: Bool {
        !saving && (!email.trimmingCharacters(in: .whitespaces).isEmpty
                    || !phone.trimmingCharacters(in: .whitespaces).isEmpty)
    }

    var body: some View {
        NavigationView {
            if handBack {
                handBackView
            } else {
                form
            }
        }
        .interactiveDismissDisabled(true)
    }

    private var form: some View {
        Form {
            Section {
                TextField("First name", text: $first).textContentType(.givenName)
                TextField("Last name", text: $last).textContentType(.familyName)
                TextField("Company", text: $company).textContentType(.organizationName)
            }
            Section {
                TextField("Phone", text: $phone)
                    .textContentType(.telephoneNumber).keyboardType(.phonePad)
                TextField("Email", text: $email)
                    .textContentType(.emailAddress).keyboardType(.emailAddress)
                    .autocapitalization(.none)
                    .onChange(of: email) { _ in emailSuggestion = nil; checkedOnce = false }
                if let sug = emailSuggestion {
                    Button {
                        email = sug; emailSuggestion = nil
                    } label: {
                        Label("Use \(sug)", systemImage: "wand.and.stars")
                            .font(.footnote.weight(.semibold))
                    }
                }
                TextField("Birthday", text: $birthday)
            } footer: {
                Text("The birthday is for a treat on the day.")
            }
            Section {
                TextField("Street address", text: $address).textContentType(.streetAddressLine1)
                TextField("Postcode", text: $postcode).textContentType(.postalCode)
                TextField("City", text: $city).textContentType(.addressCity)
                TextField("Country", text: $country).textContentType(.countryName)
            } header: {
                Text("Delivery address")
            } footer: {
                Text("For gifts, deliveries and invitations to private events.")
            }
            Section("Preferences") {
                TextField("Sizes", text: $sizes)
                TextField("Likes and interests", text: $preferences)
                TextField("Notes", text: $notes)
            }
            Section {
                Toggle("Email me about new arrivals and events", isOn: $emailUpdates)
                Toggle("Text me occasionally", isOn: $smsUpdates)
            } footer: {
                Text("Kept by the store for personal service.")
            }
            if let errorText {
                Section { Text(errorText).foregroundColor(.red).font(.footnote) }
            }
        }
        .navigationTitle("Your details")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { handBack = true }
            }
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Done") { Task { await save() } }
                    .fontWeight(.semibold)
                    .disabled(!canSave)
            }
        }
    }

    /// After Done or Cancel the phone goes back to the associate; a long-press stands between
    /// the client and the desk.
    private var handBackView: some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: savedGrade == nil && errorText == nil && !saving
                  ? "hand.wave" : "checkmark.circle")
                .font(.system(size: 44, weight: .light))
                .foregroundColor(.secondary)
            Text("Thank you").font(.title2.weight(.semibold))
            Text("Please hand the phone back.")
                .font(.system(size: 15)).foregroundColor(.secondary)
            Spacer()
            Text("Hold to continue")
                .font(.footnote).foregroundColor(.secondary)
                .padding(.vertical, 14).padding(.horizontal, 36)
                .background(Capsule().stroke(Color.secondary.opacity(0.4)))
                .onLongPressGesture(minimumDuration: 1.2) {
                    onDone(savedGrade.map { "Saved \u{00b7} Grade " + $0 } ?? (savedId != nil ? "Saved" : nil), savedId)
                    dismiss()
                }
                .padding(.bottom, 40)
        }
    }

    private func save() async {
        saving = true; errorText = nil
        // One hygiene pass before the write: a typo like gamil.com gets offered as a fix
        // while the client is still holding the phone. Best-effort; declining saves as typed.
        if !checkedOnce {
            checkedOnce = true
            let trimmedEmail = email.trimmingCharacters(in: .whitespaces)
            if let check = try? await HaliaAPI.current.checkCapture(
                email: trimmedEmail.isEmpty ? nil : trimmedEmail,
                postcode: postcode.trimmingCharacters(in: .whitespaces)) {
                if let pc = check.postcode, !pc.isEmpty { postcode = pc }
                if let sug = check.email_suggestion, !sug.isEmpty {
                    emailSuggestion = sug
                    saving = false
                    return          // surface the fix; the next Done saves either way
                }
            }
        }
        var fields: [String: Any] = ["channel": "handover"]
        for (k, v) in [("first_name", first), ("last_name", last), ("company", company),
                       ("phone", phone), ("email", email), ("birthday", birthday),
                       ("address", address), ("postcode", postcode), ("city", city), ("country", country),
                       ("sizes", sizes), ("preferences", preferences), ("notes", notes)] {
            let t = v.trimmingCharacters(in: .whitespaces)
            if !t.isEmpty { fields[k] = t }
        }
        fields["consent"] = ["email_marketing": emailUpdates, "sms_marketing": smsUpdates]
        do {
            let result = try await HaliaAPI.current.captureClient(fields)
            savedGrade = result.grade
            savedId = result.customer_id
            saving = false
            handBack = true
        } catch {
            saving = false
            errorText = "Could not save just now. Check the connection and try again."
        }
    }
}


// MARK: - Capture tools (QR codes, the associate's card)

import CoreImage.CIFilterBuiltins

/// The associate's own details, kept on-device (App Group) so the shareable card and the
/// WhatsApp QR work without any server round-trip.
private struct MyCard: Codable {
    var name = ""
    var title = ""
    var phone = ""
    var email = ""
    var signoff = ""

    static let key = "halia.mycard.json"

    static func load() -> MyCard {
        guard let d = AppGroup.defaults.data(forKey: key),
              let c = try? JSONDecoder().decode(MyCard.self, from: d) else {
            var c = MyCard()
            c.name = AppGroup.defaults.string(forKey: AppGroup.Key.name) ?? ""
            return c
        }
        return c
    }

    func save() {
        if let d = try? JSONEncoder().encode(self) { AppGroup.defaults.set(d, forKey: Self.key) }
    }

    /// Push the card to the seat on the server (best-effort): drafts and templates then sign
    /// with it everywhere, and the manager's Team panel shows the right email.
    func syncToServer() {
        let c = self
        Task { try? await HaliaAPI.current.saveProfile(name: c.name, email: c.email,
                                                        title: c.title, signoff: c.signoff) }
    }

    /// Fill empty fields from the seat's server profile (the manager may have set them).
    static func prefillFromServer() async {
        guard let p = try? await HaliaAPI.current.fetchProfile() else { return }
        var c = load(); var changed = false
        if c.name.isEmpty, let v = p.name, !v.isEmpty { c.name = v; changed = true }
        if c.email.isEmpty, let v = p.email, !v.isEmpty { c.email = v; changed = true }
        if c.title.isEmpty, let v = p.title, !v.isEmpty { c.title = v; changed = true }
        if c.signoff.isEmpty, p.default_signoff == false, let v = p.signoff, !v.isEmpty { c.signoff = v; changed = true }
        if changed { c.save() }
    }

    var firstName: String { name.split(separator: " ").first.map(String.init) ?? name }

    /// A standard vCard, so "Share my contact" hands the client a real contact card
    /// (AirDrop, WhatsApp, Messages — whatever the share sheet offers).
    var vcard: String {
        var lines = ["BEGIN:VCARD", "VERSION:3.0", "FN:\(name)"]
        let parts = name.split(separator: " ", maxSplits: 1).map(String.init)
        lines.append("N:\(parts.count > 1 ? parts[1] : "");\(parts.first ?? "");;;")
        if !title.isEmpty { lines.append("TITLE:\(title)") }
        if !phone.isEmpty { lines.append("TEL;TYPE=CELL:\(phone)") }
        if !email.isEmpty { lines.append("EMAIL:\(email)") }
        lines.append("END:VCARD")
        return lines.joined(separator: "\r\n")
    }
}

private func qrImage(for string: String) -> UIImage? {
    let filter = CIFilter.qrCodeGenerator()
    filter.message = Data(string.utf8)
    filter.correctionLevel = "M"
    guard let output = filter.outputImage else { return nil }
    let scaled = output.transformed(by: CGAffineTransform(scaleX: 11, y: 11))
    guard let cg = CIContext().createCGImage(scaled, from: scaled.extent) else { return nil }
    return UIImage(cgImage: cg)
}

private struct QRCard: View {
    let value: String
    let caption: String

    var body: some View {
        VStack(spacing: 12) {
            if let img = qrImage(for: value) {
                Image(uiImage: img)
                    .interpolation(.none)
                    .resizable().scaledToFit()
                    .frame(maxWidth: 240)
                    .padding(10).background(Color.white).cornerRadius(14)
            }
            Text(caption)
                .font(.system(size: 13)).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }
}

private struct CaptureToolsView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var card = MyCard.load()
    @State private var captureURL: String?
    @State private var vcardFile: URL?

    private var waLink: String? {
        let digits = card.phone.filter { $0.isNumber }
        guard digits.count >= 7 else { return nil }
        let msg = "Hi \(card.firstName.isEmpty ? "there" : card.firstName), please feel free to add my number."
        let enc = msg.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? msg
        return "https://wa.me/\(digits)?text=\(enc)"
    }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    if let url = captureURL {
                        QRCard(value: url,
                               caption: "The client scans this and leaves their details on their own phone. Straight into your book, graded. The address does the most for the grade.")
                    } else {
                        HStack { Spacer(); ProgressView(); Spacer() }.padding(.vertical, 30)
                    }
                } header: { Text("Self-capture") }

                Section {
                    if let wa = waLink {
                        QRCard(value: wa,
                               caption: "The client scans this and WhatsApp opens with a message to you, ready to send. One tap and you have their number.")
                    } else {
                        Text("Add your phone number below and this QR appears.")
                            .font(.system(size: 13.5)).foregroundColor(.secondary)
                    }
                } header: { Text("WhatsApp") }

                Section {
                    if let f = vcardFile {
                        ShareLink(item: f, preview: SharePreview(card.name.isEmpty ? "My contact" : card.name)) {
                            Label("Share my contact", systemImage: "square.and.arrow.up")
                        }
                    } else {
                        Text("Add your details below to share your card.")
                            .font(.system(size: 13.5)).foregroundColor(.secondary)
                    }
                } header: { Text("Your card") } footer: {
                    Text("Opens the share sheet: AirDrop, WhatsApp, Messages. The client saves you as a contact.")
                }

                Section {
                    TextField("Your name", text: $card.name)
                    TextField("Role, e.g. Client advisor", text: $card.title)
                    TextField("Phone", text: $card.phone).keyboardType(.phonePad)
                    TextField("Email", text: $card.email)
                        .keyboardType(.emailAddress).autocapitalization(.none)
                    TextField("Sign-off, e.g. Warm regards, Sarah", text: $card.signoff, axis: .vertical)
                        .lineLimit(1...3)
                } header: { Text("Your details") } footer: {
                    Text("Your name and position sign every draft. Kept with your seat, and on this device for the card and the WhatsApp QR.")
                }
            }
            .navigationTitle("Capture tools")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { card.save(); dismiss() }.fontWeight(.semibold)
                }
            }
            .onChange(of: card.name) { _ in card.save(); writeVcard() }
            .onChange(of: card.title) { _ in card.save(); writeVcard() }
            .onChange(of: card.phone) { _ in card.save(); writeVcard() }
            .onChange(of: card.email) { _ in card.save(); writeVcard() }
            .onChange(of: card.signoff) { _ in card.save() }
            .onDisappear { card.syncToServer() }
            .task {
                writeVcard()
                captureURL = try? await HaliaAPI.current.captureLink()
            }
        }
    }

    private func writeVcard() {
        let hasCard = !card.name.trimmingCharacters(in: .whitespaces).isEmpty
            && (!card.phone.isEmpty || !card.email.isEmpty)
        guard hasCard else { vcardFile = nil; return }
        let dir = FileManager.default.temporaryDirectory
        let file = dir.appendingPathComponent("contact.vcf")
        try? card.vcard.data(using: .utf8)?.write(to: file)
        vcardFile = file
    }
}

#Preview {
    RootView()
}
