// Target membership: HaliaIMessage ONLY.
//
// Agree a time in the chat and book it there. The keyboard has to do this with day pills and time
// pills because it has one row; here a real date picker fits, and the client's invitation goes
// into the conversation the moment it is booked.
import SwiftUI

struct BookTab: View {
    @ObservedObject var model: DeskModel
    @State private var when = BookTab.nextSensibleHour()
    @State private var place = ""
    @State private var minutes = 45
    @State private var busy = false
    @State private var status: String?
    @State private var message: String?

    private static func nextSensibleHour() -> Date {
        let cal = Calendar.current
        let soon = Date().addingTimeInterval(60 * 60)
        var c = cal.dateComponents([.year, .month, .day, .hour], from: soon)
        c.minute = 0
        return cal.date(from: c) ?? soon
    }

    var body: some View {
        Group {
            if !model.hasClient {
                NeedsClient(what: "book a visit")
            } else if model.cid == nil {
                VStack(spacing: 6) {
                    Text("They are not in the book yet.").font(.footnote).foregroundStyle(.secondary)
                    Text("Add them in the Halia app, then book from here.")
                        .font(.caption).foregroundStyle(Ink.soft).multilineTextAlignment(.center)
                }
                .padding(.horizontal, 30)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Form {
                    Section {
                        DatePicker("When", selection: $when,
                                   in: Date()...Date().addingTimeInterval(86_400 * 90))
                        Picker("How long", selection: $minutes) {
                            Text("30 min").tag(30)
                            Text("45 min").tag(45)
                            Text("1 hour").tag(60)
                            Text("1½ hours").tag(90)
                        }
                        TextField("Where", text: $place)
                    } header: {
                        Text("A visit for \(model.firstName.isEmpty ? "them" : model.firstName)")
                    }

                    Section {
                        Button(busy ? "Booking…" : "Book and send the invitation") {
                            Task { await book() }
                        }
                        .disabled(busy)
                        .fontWeight(.semibold)
                        .foregroundStyle(Ink.deep)
                        .frame(maxWidth: .infinity, alignment: .center)
                    } footer: {
                        Text("It goes on their record and into your own calendar in the Halia app.")
                    }

                    if let m = message {
                        Section {
                            Text(m).font(.callout)
                            Button("Put it in the chat") { model.send(m) }
                                .fontWeight(.semibold).foregroundStyle(Ink.brand)
                        } header: { Text("Their invitation") }
                    }

                    if let s = status {
                        Section { Text(s).font(.footnote).foregroundStyle(.secondary) }
                    }
                }
            }
        }
    }

    private func book() async {
        guard let cid = model.cid else { return }
        busy = true; status = nil
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        iso.timeZone = TimeZone.current
        do {
            let res = try await HaliaAPI.current.bookAppointment(
                cid: cid, when: iso.string(from: when), place: place,
                clientName: model.name, clientEmail: model.email)
            if let m = res.links?.message, !m.isEmpty {
                message = m
                model.send(m)          // straight into the chat; it is why they are here
            } else {
                status = "Booked, but the invitation did not come back."
            }
        } catch {
            status = (error as? LocalizedError)?.errorDescription ?? "Could not book that time."
        }
        busy = false
    }
}
