// Target membership: HaliaWidget (the widget extension) ONLY.
// Also add the Shared/ files to this target: HaliaAPI.swift, Credentials.swift, AppGroup.swift.
//
// "Reach today" — a Home / Lock Screen widget showing Halia's proactive queue: new orders from top
// clients to acknowledge and proven clients gone quiet to win back. Reads /v1/extension/today with
// the App Group token the host app already stores. Signed out -> a prompt to open Halia. Zero
// retention: the timeline holds only what a glance needs, and iOS discards it on its own schedule.
import WidgetKit
import SwiftUI

struct TodayEntry: TimelineEntry {
    let date: Date
    let label: String
    let items: [HaliaAPI.TodayItem]
    let signedIn: Bool
}

struct TodayProvider: TimelineProvider {
    static let sample = TodayEntry(
        date: Date(), label: "Halia",
        items: [
            .init(kind: "new_order",  name: "Amelia Hart",  grade: "A*", text: "New order · send a personal note", cid: "1"),
            .init(kind: "gone_quiet", name: "James Fenn",   grade: "A",  text: "Gone quiet · reach out",          cid: "2"),
            .init(kind: "gone_quiet", name: "Sofia Duarte", grade: "A",  text: "Gone quiet · reach out",          cid: "3"),
        ], signedIn: true)

    func placeholder(in context: Context) -> TodayEntry { Self.sample }

    func getSnapshot(in context: Context, completion: @escaping (TodayEntry) -> Void) {
        if context.isPreview || !Credentials.hasToken { completion(Self.sample); return }
        Task { completion(await fetch()) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TodayEntry>) -> Void) {
        Task {
            let entry = Credentials.hasToken
                ? await fetch()
                : TodayEntry(date: Date(), label: "Halia", items: [], signedIn: false)
            // Refresh ~every 30 min; iOS budgets the real reload rate.
            let next = Calendar.current.date(byAdding: .minute, value: 30, to: Date())
                ?? Date().addingTimeInterval(1800)
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }

    private func fetch() async -> TodayEntry {
        do {
            let (label, items) = try await HaliaAPI.current.today()
            return TodayEntry(date: Date(), label: label, items: items, signedIn: true)
        } catch {
            // On a transient failure, show an empty (not error) state; the next reload retries.
            return TodayEntry(date: Date(), label: "Halia", items: [], signedIn: true)
        }
    }
}

// Brand palette (no gold): A* = charcoal, A = green, B = slate, else grey.
private func gradeColor(_ g: String) -> Color {
    switch g.uppercased() {
    case "A*": return Color(red: 0.10, green: 0.11, blue: 0.13)
    case "A":  return Color(red: 0.12, green: 0.34, blue: 0.29)
    case "B":  return Color(red: 0.37, green: 0.42, blue: 0.45)
    default:   return Color(red: 0.55, green: 0.56, blue: 0.59)
    }
}
private let brandGreen = Color(red: 0.12, green: 0.34, blue: 0.29)

struct TodayWidgetView: View {
    @Environment(\.widgetFamily) var family
    var entry: TodayEntry

    var body: some View {
        content.haliaWidgetBackground(family == .accessoryRectangular ? .clear : Color(.systemBackground))
    }

    @ViewBuilder private var content: some View {
        if family == .accessoryRectangular { lockView }
        else { homeView }
    }

    // Home / Lock (StandBy) rectangular families
    private var homeView: some View {
        let rows = family == .systemSmall ? 3 : 4
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text("⁂").foregroundColor(brandGreen).font(.system(size: 13, weight: .bold))
                Text("Reach today").font(.system(size: 12, weight: .semibold))
                    .foregroundColor(.secondary).textCase(.uppercase).kerning(0.4)
                Spacer()
                if entry.signedIn && !entry.items.isEmpty {
                    Text("\(entry.items.count)")
                        .font(.system(size: 12, weight: .bold, design: .rounded))
                        .foregroundColor(brandGreen)
                }
            }
            if !entry.signedIn {
                emptyMessage("Open Halia to connect your store.")
            } else if entry.items.isEmpty {
                emptyMessage("You're clear. No one flagged to reach.")
            } else {
                ForEach(entry.items.prefix(rows)) { item in row(item) }
                Spacer(minLength: 0)
            }
        }
        .padding(family == .systemSmall ? 12 : 14)
        .widgetURL(URL(string: "halia://today"))
    }

    private func row(_ item: HaliaAPI.TodayItem) -> some View {
        HStack(spacing: 8) {
            Circle().fill(gradeColor(item.grade)).frame(width: 7, height: 7)
            Text(item.name).font(.system(size: 13, weight: .medium)).lineLimit(1)
            Spacer(minLength: 4)
            Text(item.isNewOrder ? "new order" : "gone quiet")
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(item.isNewOrder ? brandGreen : .secondary)
                .lineLimit(1)
        }
    }

    private func emptyMessage(_ s: String) -> some View {
        Text(s).font(.system(size: 13)).foregroundColor(.secondary)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    // Lock Screen rectangular complication
    private var lockView: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Reach today").font(.system(size: 11, weight: .semibold)).textCase(.uppercase)
            if !entry.signedIn {
                Text("Open Halia").font(.system(size: 13))
            } else if entry.items.isEmpty {
                Text("You're clear").font(.system(size: 14, weight: .semibold))
            } else {
                Text("\(entry.items.count) to reach").font(.system(size: 15, weight: .semibold))
                if let first = entry.items.first {
                    Text(first.name).font(.system(size: 12)).lineLimit(1)
                }
            }
        }
        .widgetURL(URL(string: "halia://today"))
    }
}

struct TodayWidget: Widget {
    let kind = "HaliaTodayWidget"
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: TodayProvider()) { entry in
            TodayWidgetView(entry: entry)
        }
        .configurationDisplayName("Reach today")
        .description("The clients Halia says to reach today.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular])
    }
}

extension View {
    /// containerBackground on iOS 17+, a plain background before that, so the widget builds on both.
    @ViewBuilder func haliaWidgetBackground(_ color: Color) -> some View {
        if #available(iOS 17.0, *) { self.containerBackground(color, for: .widget) }
        else { self.background(color) }
    }
}
