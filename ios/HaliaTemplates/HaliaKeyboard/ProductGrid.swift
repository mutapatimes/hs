// Target membership: KEYBOARD EXTENSION ONLY.
//
// The product library's plumbing: a downsampling thumbnail loader (keyboard extensions have a tight
// memory budget, so images are decoded straight to small thumbnails and cached), and the grid cell.
import UIKit
import ImageIO

final class ThumbnailLoader {
    static let shared = ThumbnailLoader()
    private let cache = NSCache<NSURL, UIImage>()
    private let maxPixel: CGFloat = 240 * UIScreen.main.scale   // thumbnail budget, in pixels

    init() { cache.countLimit = 120 }

    /// Load `url` into `imageView`, guarding against cell reuse via a token.
    func load(_ url: URL, into imageView: UIImageView, token: Int) {
        if let img = cache.object(forKey: url as NSURL) { imageView.image = img; return }
        URLSession.shared.dataTask(with: url) { [weak self, weak imageView] data, _, _ in
            guard let self = self, let data = data, let img = self.downsample(data) else { return }
            self.cache.setObject(img, forKey: url as NSURL)
            DispatchQueue.main.async {
                if let iv = imageView, iv.tag == token { iv.image = img }
            }
        }.resume()
    }

    private func downsample(_ data: Data) -> UIImage? {
        let opts: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
        ]
        guard let src = CGImageSourceCreateWithData(data as CFData, nil),
              let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
        else { return UIImage(data: data) }
        return UIImage(cgImage: cg)
    }
}

final class ProductCell: UICollectionViewCell {
    static let id = "product"
    let img = UIImageView()
    let cap = UILabel()

    override init(frame: CGRect) {
        super.init(frame: frame)
        img.contentMode = .scaleAspectFill
        img.clipsToBounds = true
        img.backgroundColor = UIColor(white: 0.92, alpha: 1)
        img.layer.cornerRadius = 10
        img.translatesAutoresizingMaskIntoConstraints = false
        cap.font = .systemFont(ofSize: 11, weight: .medium)
        cap.textColor = .secondaryLabel
        cap.numberOfLines = 1
        cap.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(img)
        contentView.addSubview(cap)
        NSLayoutConstraint.activate([
            img.topAnchor.constraint(equalTo: contentView.topAnchor),
            img.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
            img.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
            img.heightAnchor.constraint(equalTo: img.widthAnchor),
            cap.topAnchor.constraint(equalTo: img.bottomAnchor, constant: 4),
            cap.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 1),
            cap.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("not used") }

    override func prepareForReuse() {
        super.prepareForReuse()
        img.image = nil
        cap.text = nil
    }
}
