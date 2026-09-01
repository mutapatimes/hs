// Target membership: HaliaIMessage ONLY.
//
// A note written for this client, in the house voice. The keyboard drafts into a strip; here the
// draft is readable and editable before it goes anywhere, which is the whole point of the room.
import SwiftUI

struct DraftTab: View {
    @ObservedObject var model: DeskModel
    @State private var instruction = ""
    @State private var text = ""
    @State private var busy = false
    @State private var status: String?

    /// The moves an associate actually asks for, so the common case is one tap.
    private static let angles = [
        ("Warm hello", "a warm hello, nothing to sell"),
        ("New in", "tell them what has just come in"),
        ("Their size", "something in their size is back"),
        ("Invite in", "invite them in to see it"),
        ("Follow up", "follow up on our last conversation"),
        ("Thank you", "thank them for their visit"),
    ]

    var body: some View {
        Group {
            if !model.hasClient {
                NeedsClient(what: "draft a note")
            } else {
                VStack(spacing: 0) {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Self.angles, id: \.0) { label, ask in
                                Button(label) { instruction = ask; Task { await write() } }
                                    .font(.footnote.weight(.semibold))
                                    .foregroundStyle(Ink.deep)
                                    .padding(.horizontal, 11).padding(.vertical, 7)
                                    .background(Capsule().fill(Color.secondary.opacity(0.12)))
                            }
                        }
                        .padding(.horizontal, 12)
                    }
                    .padding(.vertical, 8)

                    HStack(spacing: 8) {
                        TextField("Or say what to write", text: $instruction, axis: .vertical)
                            .textFieldStyle(.roundedBorder)
                            .lineLimit(1...3)
                        Button(busy ? "…" : "Write") { Task { await write() } }
                            .font(.footnote.weight(.semibold)).foregroundStyle(Ink.brand)
                            .disabled(busy)
                    }
                    .padding(.horizontal, 12)

                    if let s = status {
                        HStack { Text(s).font(.caption).foregroundStyle(Ink.soft); Spacer() }
                            .padding(.horizontal, 14).padding(.top, 6)
                    }

                    if text.isEmpty {
                        VStack(spacing: 6) {
                            if busy { ProgressView() }
                            Text(busy ? "Writing…" : "Pick an angle, or say what to write.")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        TextEditor(text: $text)
                            .font(.callout)
                            .padding(.horizontal, 8)
                            .frame(maxHeight: .infinity)
                    }

                    if !text.isEmpty {
                        SendBar(title: "Put it in the chat", enabled: !busy) { model.send(text) }
                    }
                }
            }
        }
    }

    private func write() async {
        guard let ref = model.ref else { return }
        let ask = instruction.trimmingCharacters(in: .whitespaces)
        guard !ask.isEmpty else { status = "Say what to write, or pick an angle."; return }
        busy = true; status = nil
        do {
            let r = try await HaliaAPI.current.draft(ref, channel: "imessage", instruction: ask)
            text = r.draft ?? ""
            if text.isEmpty { status = "Nothing came back. Try saying it another way." }
        } catch {
            status = (error as? LocalizedError)?.errorDescription ?? "Could not reach Halia."
        }
        busy = false
    }
}
