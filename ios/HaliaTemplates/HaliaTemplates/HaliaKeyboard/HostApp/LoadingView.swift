// Target membership: HaliaTemplates (host app) ONLY.
//
// SwiftUI versions of Halia's loading motifs, so the app's "Syncing…" matches the keyboard and the
// web: a 3x3 pixel-grid loader with a chevron wavefront, a shimmering label, and a live elapsed
// timer. Respects Reduce Motion.
import SwiftUI

private let haliaGreen = Color(red: 0.122, green: 0.337, blue: 0.290)

/// A small squared-off pixel-grid loader (matches the web `.pxgrid` / the keyboard's PixelLoader).
struct PixelGridLoader: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var on = false

    var body: some View {
        VStack(spacing: 1) {
            ForEach(0..<3, id: \.self) { r in
                HStack(spacing: 1) {
                    ForEach(0..<3, id: \.self) { c in
                        Rectangle()
                            .fill(haliaGreen)
                            .frame(width: 5, height: 5)
                            .opacity(on ? 0.9 : 0.18)
                            .animation(
                                reduceMotion ? nil :
                                    .easeInOut(duration: 0.325).repeatForever(autoreverses: true)
                                    .delay(Double(c + abs(r - 1)) * 0.09),   // chevron wavefront
                                value: on)
                    }
                }
            }
        }
        .onAppear { if !reduceMotion { on = true } }
    }
}

/// A label whose text sweeps a soft highlight left to right (matches the web `.shim`).
struct ShimmerText: View {
    let text: String
    var font: Font = .system(size: 14, weight: .medium)
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var move = false

    var body: some View {
        Text(text)
            .font(font)
            .foregroundStyle(.secondary)
            .overlay {
                if !reduceMotion {
                    GeometryReader { geo in
                        LinearGradient(colors: [.clear, .primary.opacity(0.9), .clear],
                                       startPoint: .leading, endPoint: .trailing)
                            .frame(width: geo.size.width * 0.55)
                            .offset(x: move ? geo.size.width : -geo.size.width * 0.55)
                            .mask(Text(text).font(font))
                    }
                }
            }
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.linear(duration: 1.15).repeatForever(autoreverses: false)) { move = true }
            }
    }
}

/// Pixel loader + shimmering label + live elapsed timer, for any in-flight operation.
struct HaliaLoadingRow: View {
    var label: String = ""
    @State private var start = Date()
    @State private var now = Date()
    private let ticker = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 10) {
            PixelGridLoader()
            if !label.isEmpty {
                ShimmerText(text: label, font: .system(size: 13.5, weight: .medium))
            }
            Text(elapsed)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(.tertiary)
        }
        .onReceive(ticker) { now = $0 }
    }

    private var elapsed: String {
        let t = now.timeIntervalSince(start)
        return t < 60 ? String(format: "%.1fs", t)
            : String(format: "%dm %.0fs", Int(t) / 60, t.truncatingRemainder(dividingBy: 60))
    }
}
