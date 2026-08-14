// Target membership: HaliaKeyboard extension.
//
// Native UIKit versions of Halia's web loading motifs, so the keyboard feels alive while it drafts,
// searches, or builds a catalogue: a 3x3 pixel-grid loader with a chevron wavefront, and a shimmer
// label. Both freeze gracefully under Reduce Motion.
import UIKit

/// The Halia brand green (no gold), used for the loader dots.
private let haliaGreen = UIColor(red: 0.122, green: 0.337, blue: 0.290, alpha: 1)

/// A small squared-off pixel-grid loader (matches the web `.pxgrid` loader).
final class PixelLoader: UIView {
    private let dots: [CALayer]

    override init(frame: CGRect) {
        dots = (0..<9).map { _ in CALayer() }
        super.init(frame: frame)
        translatesAutoresizingMaskIntoConstraints = false
        for d in dots {
            d.backgroundColor = haliaGreen.cgColor
            d.opacity = 0.18
            layer.addSublayer(d)
        }
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 17),
            heightAnchor.constraint(equalToConstant: 17),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        let s: CGFloat = 5, gap: CGFloat = 1
        for i in 0..<9 {
            let r = i / 3, c = i % 3
            dots[i].frame = CGRect(x: CGFloat(c) * (s + gap), y: CGFloat(r) * (s + gap), width: s, height: s)
        }
        animate()
    }

    private func animate() {
        guard !UIAccessibility.isReduceMotionEnabled else { return }
        for i in 0..<9 {
            let r = i / 3, c = i % 3
            dots[i].removeAnimation(forKey: "pulse")
            let a = CABasicAnimation(keyPath: "opacity")
            a.fromValue = 0.18
            a.toValue = 0.9
            a.duration = 0.325
            a.autoreverses = true
            a.repeatCount = .infinity
            a.beginTime = CACurrentMediaTime() + Double(c + abs(r - 1)) * 0.09   // chevron wavefront
            a.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            dots[i].add(a, forKey: "pulse")
        }
    }
}

/// A label whose text sweeps a soft highlight left-to-right (matches the web `.shim` shimmer). Text
/// stays visible throughout (the mask never drops below ~50% opacity).
final class ShimmerLabel: UILabel {
    private let sweep = CAGradientLayer()

    override init(frame: CGRect) {
        super.init(frame: frame)
        sweep.startPoint = CGPoint(x: 0, y: 0.5)
        sweep.endPoint = CGPoint(x: 1, y: 0.5)
        sweep.colors = [
            UIColor(white: 1, alpha: 0.5).cgColor,
            UIColor(white: 1, alpha: 1.0).cgColor,
            UIColor(white: 1, alpha: 0.5).cgColor,
        ]
        sweep.locations = [0, 0.5, 1]
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        sweep.frame = bounds
        layer.mask = sweep
        guard !UIAccessibility.isReduceMotionEnabled else { layer.mask = nil; return }
        sweep.removeAnimation(forKey: "shimmer")
        let a = CABasicAnimation(keyPath: "locations")
        a.fromValue = [-0.5, 0.0, 0.5]
        a.toValue = [0.5, 1.0, 1.5]
        a.duration = 1.15
        a.repeatCount = .infinity
        sweep.add(a, forKey: "shimmer")
    }
}
