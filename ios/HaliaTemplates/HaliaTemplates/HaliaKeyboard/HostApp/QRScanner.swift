// Target membership: HOST APP ONLY.
//
// In-app QR scanning for the connect step: point the camera at the code shown in the Halia
// dashboard (a halia://connect?t=…&b=… payload) and we read the token straight off it, so the
// merchant never types or copies anything. Nothing is recorded; the session stops the moment a
// code is read.
import SwiftUI
import AVFoundation

/// A full-screen camera scanner. Calls `onCode` once with the first QR string it sees, then the
/// presenter dismisses it. Handles the not-authorised case with a route into Settings.
struct QRScanner: View {
    let onCode: (String) -> Void
    let onCancel: () -> Void

    @State private var authorized: Bool? = nil   // nil = still asking

    private let brandDeep = Color(red: 0.055, green: 0.180, blue: 0.153)

    var body: some View {
        ZStack {
            brandDeep.ignoresSafeArea()
            switch authorized {
            case .some(true):
                CameraLayer(onCode: onCode)
                    .ignoresSafeArea()
                reticle
            case .some(false):
                denied
            case .none:
                ProgressView().tint(.white)
            }

            VStack {
                HStack {
                    Button(action: onCancel) {
                        Text("Cancel").font(.system(size: 16, weight: .semibold)).foregroundColor(.white)
                            .padding(.horizontal, 16).padding(.vertical, 10)
                            .background(Capsule().fill(.black.opacity(0.35)))
                    }
                    .buttonStyle(.plain)
                    Spacer()
                }
                Spacer()
                if authorized == true {
                    Text("Point at the code in your Halia dashboard")
                        .font(.system(size: 15)).foregroundColor(.white.opacity(0.9))
                        .padding(.bottom, 48)
                }
            }
            .padding(20)
        }
        .task { await requestAccess() }
    }

    private var reticle: some View {
        RoundedRectangle(cornerRadius: 24)
            .stroke(.white.opacity(0.9), lineWidth: 3)
            .frame(width: 240, height: 240)
    }

    private var denied: some View {
        VStack(spacing: 16) {
            Image(systemName: "camera.fill").font(.system(size: 34)).foregroundColor(.white.opacity(0.9))
            Text("Camera access is off")
                .font(.system(size: 20, weight: .semibold, design: .serif)).foregroundColor(.white)
            Text("Turn it on in Settings to scan your connect code, or paste a token instead.")
                .font(.system(size: 14)).foregroundColor(.white.opacity(0.8))
                .multilineTextAlignment(.center).padding(.horizontal, 40)
            Button {
                if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
            } label: {
                Text("Open Settings").font(.system(size: 15, weight: .semibold)).foregroundColor(brandDeep)
                    .padding(.horizontal, 22).padding(.vertical, 12)
                    .background(RoundedRectangle(cornerRadius: 13).fill(.white))
            }
            .buttonStyle(.plain)
        }
    }

    private func requestAccess() async {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            authorized = true
        case .notDetermined:
            authorized = await AVCaptureDevice.requestAccess(for: .video)
        default:
            authorized = false
        }
    }
}

/// UIKit camera preview that emits the first QR payload it reads.
private struct CameraLayer: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        let vc = ScannerController()
        vc.onCode = onCode
        return vc
    }
    func updateUIViewController(_ uiViewController: ScannerController, context: Context) {}
}

private final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let session = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?
    private var handled = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return }
        session.addInput(input)

        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        preview = layer
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        guard !session.isRunning else { return }
        // startRunning blocks; keep it off the main thread.
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.session.startRunning() }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning { DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.session.stopRunning() } }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput,
                        didOutput metadataObjects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        guard !handled,
              let obj = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
              let value = obj.stringValue else { return }
        handled = true
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        onCode?(value)
    }
}
