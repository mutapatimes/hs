// Target membership: HOST APP ONLY. The app entry point.
import SwiftUI

@main
struct HaliaTemplatesApp: App {
    @Environment(\.scenePhase) private var phase

    init() {
        AppGroup.excludeFromBackup()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                // The app switcher snapshots the screen; a client's name and grade stay out of it.
                .overlay {
                    if phase != .active { PrivacyCover() }
                }
        }
    }
}

private struct PrivacyCover: View {
    var body: some View {
        ZStack {
            Color(.systemBackground).ignoresSafeArea()
            Text("Halia")
                .font(.system(.title2, design: .serif))
                .foregroundStyle(.secondary)
        }
    }
}
