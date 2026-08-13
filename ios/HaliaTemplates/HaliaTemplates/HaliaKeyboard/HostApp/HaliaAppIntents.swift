// Target membership: HaliaTemplates (the host app) ONLY. Reuses Shared/ (HaliaAPI, Credentials).
//
// App Intents are the multiplier: one definition surfaces Halia across Siri, the Shortcuts app,
// Spotlight, and Lock Screen / Control Center buttons. "Who to reach today" reads the same
// /v1/extension/today queue the widget uses. Zero retention: it fetches live and returns speech.
import AppIntents

@available(iOS 16.0, *)
struct WhoToReachTodayIntent: AppIntent {
    static var title: LocalizedStringResource = "Who to reach today"
    static var description = IntentDescription(
        "Halia's clients to reach today: new orders to acknowledge and proven clients gone quiet.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard Credentials.hasToken else {
            return .result(dialog: "Open Halia and connect your store first.")
        }
        let (_, items) = try await HaliaAPI.current.today()
        guard !items.isEmpty else {
            return .result(dialog: "No one flagged to reach right now. You're clear.")
        }
        let names = items.prefix(3).map { $0.name }
        let list = ListFormatter.localizedString(byJoining: names)
        let more = items.count > 3 ? ", and \(items.count - 3) more" : ""
        let count = items.count
        return .result(dialog: "\(count) to reach today: \(list)\(more).")
    }
}

@available(iOS 16.0, *)
struct HaliaShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: WhoToReachTodayIntent(),
            phrases: [
                "Who should I reach today in \(.applicationName)",
                "\(.applicationName) reach today",
                "Ask \(.applicationName) who to contact",
            ],
            shortTitle: "Reach today",
            systemImageName: "person.2.wave.2.fill")
    }
}
