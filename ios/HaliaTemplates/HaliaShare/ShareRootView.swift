// Target membership: HaliaShare (the Share extension) ONLY.
//
// The card shown when you share a client into Halia: who they are, their grade, why they surfaced,
// any open basket, and one tap to draft a message in the house voice that you can copy back to the
// chat. Reuses HaliaAPI.lookup + draft. Nothing is stored.
import SwiftUI
import UIKit

struct ShareRootView: View {
    let query: String
    let onClose: () -> Void

    @State private var phase: Phase = .loading
    @State private var result: HaliaAPI.LookupResult?
    @State private var draft = ""
    @State private var drafting = false
    @State private var copied = false

    enum Phase { case loading, found, notfound, signedOut, error(String) }

    private let green = Color(red: 0.12, green: 0.34, blue: 0.29)

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    switch phase {
                    case .loading:    loading
                    case .signedOut:  message("Open Halia and connect your store first.")
                    case .notfound:   message("No Halia signal for “\(query)”. Not a flagged client in your book.")
                    case .error(let e): message(e)
                    case .found:      found
                    }
                }
                .padding(18)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 6) {
                        Text("⁂").foregroundColor(green).font(.system(size: 15, weight: .bold))
                        Text("Halia").font(.system(size: 16, weight: .semibold))
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done", action: onClose)
                }
            }
        }
        .task { await run() }
    }

    // MARK: states

    private var loading: some View {
        HStack(spacing: 10) {
            ProgressView()
            Text("Looking up \(query)…").foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func message(_ s: String) -> some View {
        Text(s).foregroundColor(.secondary).frame(maxWidth: .infinity, alignment: .leading)
    }

    private var found: some View {
        let r = result
        return VStack(alignment: .leading, spacing: 16) {
            // name + grade
            HStack(spacing: 10) {
                if let g = r?.grade, !g.isEmpty {
                    Text(g)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(.white)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(gradeColor(g))
                }
                Text(r?.name ?? query).font(.system(size: 20, weight: .semibold))
                Spacer()
            }
            if let latent = r?.latent, !latent.isEmpty {
                Text("\(latent) latent value").font(.system(size: 13)).foregroundColor(.secondary)
            }
            // open basket
            if let cart = r?.cart, let count = cart.count, count > 0 {
                Text("Open basket · \(count) item\(count == 1 ? "" : "s")")
                    .font(.system(size: 13, weight: .medium)).foregroundColor(green)
            }
            // reasons
            if let reasons = r?.reasons, !reasons.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("WHY THIS CLIENT SURFACED")
                        .font(.system(size: 10, weight: .semibold)).foregroundColor(.secondary).kerning(0.5)
                    ForEach(reasons.prefix(4), id: \.self) { why in
                        HStack(alignment: .top, spacing: 8) {
                            Text("·").foregroundColor(green).bold()
                            Text(why).font(.system(size: 13)).foregroundColor(.primary)
                        }
                    }
                }
            }
            Divider()
            // draft
            if draft.isEmpty {
                Button(action: { Task { await makeDraft() } }) {
                    HStack {
                        if drafting { ProgressView().tint(.white) }
                        Text(drafting ? "Drafting…" : "Draft a message")
                            .font(.system(size: 15, weight: .semibold)).foregroundColor(.white)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 12).background(green)
                }
                .disabled(drafting)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    Text(draft).font(.system(size: 14)).foregroundColor(.primary)
                        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(.secondarySystemBackground))
                    Button(action: copyDraft) {
                        Text(copied ? "Copied ✓" : "Copy reply")
                            .font(.system(size: 15, weight: .semibold)).foregroundColor(.white)
                            .frame(maxWidth: .infinity).padding(.vertical, 12).background(green)
                    }
                }
            }
        }
    }

    // MARK: actions

    private func run() async {
        guard Credentials.hasToken else { phase = .signedOut; return }
        guard let ref = ClientClassifier.classify(query) else { phase = .notfound; return }
        phase = .loading
        do {
            let r = try await HaliaAPI.current.lookup(ref)
            result = r
            phase = (r.found == true) ? .found : .notfound
        } catch {
            phase = .error((error as? HaliaAPIError)?.errorDescription ?? "Could not reach Halia.")
        }
    }

    private func makeDraft() async {
        guard let ref = ClientClassifier.classify(query) else { return }
        drafting = true
        defer { drafting = false }
        if let d = try? await HaliaAPI.current.draft(ref, channel: "message", instruction: "") {
            draft = d.draft ?? ""
        }
    }

    private func copyDraft() {
        UIPasteboard.general.string = draft
        copied = true
    }

    // Brand grade colours (no gold): A* charcoal, A green, B slate, else grey.
    private func gradeColor(_ g: String) -> Color {
        switch g.uppercased() {
        case "A*": return Color(red: 0.10, green: 0.11, blue: 0.13)
        case "A":  return green
        case "B":  return Color(red: 0.37, green: 0.42, blue: 0.45)
        default:   return Color(red: 0.55, green: 0.56, blue: 0.59)
        }
    }
}
