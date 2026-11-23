import AVFoundation
import CoreImage
import SwiftUI
import UIKit

/// Camera mode: the phone stands in front of the TV and reads the English subtitle off the
/// screen with the back camera. Nothing talks to the console, so the game is not affected at all
/// and any console works. The TV picture is expected to fill the guide frame on screen; that part
/// of the camera image is cut out and handed to the same reader as Remote Play (FrameTap).
final class CameraReader: NSObject, ObservableObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    /// The guide frame inside the camera picture (top-left origin, 0...1). The picture is 16:9,
    /// like the TV, so the frame is a centred 16:9 box with a small margin.
    static let guide = CGRect(x: 0.04, y: 0.04, width: 0.92, height: 0.92)
    /// Seconds between frames sent to the reader (it reads at most one at a time anyway).
    private let interval: CFAbsoluteTime = 0.25

    let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "playtranslate.camera", qos: .userInitiated)
    private let ci = CIContext(options: [.cacheIntermediates: false])
    private var device: AVCaptureDevice?
    private var lastSent: CFAbsoluteTime = 0
    private var pool: CVPixelBufferPool?
    private var poolSize = CGSize.zero

    @Published var permissionDenied = false
    @Published var noCamera = false
    @Published var maxZoom: CGFloat = 1

    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndRun()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { ok in
                DispatchQueue.main.async {
                    if ok { self.configureAndRun() } else { self.permissionDenied = true }
                }
            }
        default:
            permissionDenied = true
        }
    }

    func stop() {
        queue.async { if self.session.isRunning { self.session.stopRunning() } }
    }

    func setZoom(_ factor: CGFloat) {
        queue.async {
            guard let dev = self.device, (try? dev.lockForConfiguration()) != nil else { return }
            dev.videoZoomFactor = max(1, min(factor, dev.activeFormat.videoMaxZoomFactor))
            dev.unlockForConfiguration()
        }
    }

    /// Frames are rotated to match the screen, so the guide frame maps 1:1 onto the picture.
    func setOrientation(_ o: AVCaptureVideoOrientation) {
        queue.async {
            if let c = self.output.connection(with: .video), c.isVideoOrientationSupported {
                c.videoOrientation = o
            }
        }
    }

    private func configureAndRun() {
        queue.async { [self] in
            if session.inputs.isEmpty {
                session.beginConfiguration()
                // 4K keeps small subtitles readable from the sofa; 1080p on older phones.
                session.sessionPreset = session.canSetSessionPreset(.hd4K3840x2160) ? .hd4K3840x2160 : .hd1920x1080
                guard let dev = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                      let input = try? AVCaptureDeviceInput(device: dev), session.canAddInput(input) else {
                    session.commitConfiguration()
                    DispatchQueue.main.async { self.noCamera = true }
                    return
                }
                session.addInput(input)
                device = dev
                output.alwaysDiscardsLateVideoFrames = true
                output.setSampleBufferDelegate(self, queue: queue)
                if session.canAddOutput(output) { session.addOutput(output) }
                session.commitConfiguration()
                if (try? dev.lockForConfiguration()) != nil {
                    if dev.isFocusModeSupported(.continuousAutoFocus) { dev.focusMode = .continuousAutoFocus }
                    if dev.isExposureModeSupported(.continuousAutoExposure) { dev.exposureMode = .continuousAutoExposure }
                    dev.unlockForConfiguration()
                }
                let maxZ = min(dev.activeFormat.videoMaxZoomFactor, 5)
                DispatchQueue.main.async { self.maxZoom = maxZ }
            }
            if !session.isRunning { session.startRunning() }
        }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let now = CFAbsoluteTimeGetCurrent()
        guard now - lastSent >= interval, let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastSent = now
        guard let tv = cutOutGuide(pixels) else { return }
        FrameTap.shared.feed(tv, camera: true)
    }

    /// The part of the camera picture inside the guide frame, as its own upright image.
    private func cutOutGuide(_ pixels: CVPixelBuffer) -> CVPixelBuffer? {
        let w = CGFloat(CVPixelBufferGetWidth(pixels)), h = CGFloat(CVPixelBufferGetHeight(pixels))
        let g = CameraReader.guide
        // Core Image counts y from the bottom.
        let rect = CGRect(x: g.minX * w, y: (1 - g.maxY) * h, width: g.width * w, height: g.height * h).integral
        guard rect.width >= 16, rect.height >= 16 else { return nil }
        let image = CIImage(cvPixelBuffer: pixels)
            .cropped(to: rect)
            .transformed(by: CGAffineTransform(translationX: -rect.minX, y: -rect.minY))
        if pool == nil || poolSize != rect.size {
            let attrs: [String: Any] = [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: Int(rect.width),
                kCVPixelBufferHeightKey as String: Int(rect.height),
                kCVPixelBufferIOSurfacePropertiesKey as String: [String: Any](),
            ]
            var newPool: CVPixelBufferPool?
            CVPixelBufferPoolCreate(kCFAllocatorDefault, nil, attrs as CFDictionary, &newPool)
            pool = newPool
            poolSize = rect.size
        }
        guard let pool else { return nil }
        var out: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &out)
        guard let out else { return nil }
        ci.render(image, to: out)
        return out
    }
}

/// Live camera picture, letterboxed (never cropped) so the guide frame matches the picture exactly.
final class CameraPreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    var onOrientation: ((AVCaptureVideoOrientation) -> Void)?

    override func layoutSubviews() {
        super.layoutSubviews()
        let o: AVCaptureVideoOrientation
        switch window?.windowScene?.interfaceOrientation ?? .landscapeRight {
        case .landscapeLeft: o = .landscapeLeft
        case .portrait: o = .portrait
        case .portraitUpsideDown: o = .portraitUpsideDown
        default: o = .landscapeRight
        }
        if let c = previewLayer.connection, c.isVideoOrientationSupported, c.videoOrientation != o {
            c.videoOrientation = o
        }
        onOrientation?(o)
    }
}

struct CameraPreview: UIViewRepresentable {
    let reader: CameraReader

    func makeUIView(context: Context) -> CameraPreviewView {
        let v = CameraPreviewView()
        v.backgroundColor = .black
        v.previewLayer.session = reader.session
        v.previewLayer.videoGravity = .resizeAspect
        v.onOrientation = { [weak reader] o in reader?.setOrientation(o) }
        return v
    }

    func updateUIView(_ uiView: CameraPreviewView, context: Context) {}
}

/// Full-screen camera mode, opened from the translation tab.
struct CameraModeView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var reader = CameraReader()
    @State private var zoom: CGFloat = 1
    @State private var status = BroadcastStatus.load()
    private let settings = Settings.load()
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CameraPreview(reader: reader).ignoresSafeArea()
            guideOverlay.ignoresSafeArea()
            VStack {
                topBar
                Spacer()
                bottomBar
            }
            .padding()
            if reader.permissionDenied || reader.noCamera { blockedMessage }
        }
        .environment(\.layoutDirection, .rightToLeft)
        .statusBarHidden()
        .onAppear {
            AppOrientationLock.lockLandscapeForStream()
            reader.start()
        }
        .onDisappear {
            reader.stop()
            FrameTap.shared.stop()
            AppOrientationLock.unlockAfterStream()
        }
        .onReceive(timer) { _ in status = BroadcastStatus.load() }
    }

    /// The 16:9 frame the TV must fill, with the read area (blue) inside it.
    private var guideOverlay: some View {
        GeometryReader { geo in
            let video = AVMakeRect(aspectRatio: CGSize(width: 16, height: 9),
                                   insideRect: CGRect(origin: .zero, size: geo.size))
            let g = CameraReader.guide
            let frame = CGRect(x: video.minX + g.minX * video.width, y: video.minY + g.minY * video.height,
                               width: g.width * video.width, height: g.height * video.height)
            let r = settings.effectiveRegion
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 10)
                    .stroke(Color.white.opacity(0.9), style: StrokeStyle(lineWidth: 3, dash: [14, 8]))
                    .frame(width: frame.width, height: frame.height)
                    .offset(x: frame.minX, y: frame.minY)
                Rectangle()
                    .fill(Color.blue.opacity(0.18))
                    .overlay(Rectangle().stroke(Color.blue, lineWidth: 2))
                    .frame(width: r.width * frame.width, height: r.height * frame.height)
                    .offset(x: frame.minX + r.minX * frame.width, y: frame.minY + r.minY * frame.height)
            }
            .environment(\.layoutDirection, .leftToRight)
        }
        .allowsHitTesting(false)
    }

    private var topBar: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Circle().fill(status.isLive ? Color.green : Color.gray).frame(width: 10, height: 10)
                    Text(status.isLive ? (status.tvCount > 0 ? "يقرأ ✓ التلفزيون متصل" : "يقرأ… ينتظر التلفزيون")
                                       : "وجّه الكاميرا على التلفزيون")
                        .bold()
                }
                if !status.lastEnglish.isEmpty {
                    Text(status.lastEnglish).font(.caption).lineLimit(1)
                        .environment(\.layoutDirection, .leftToRight)
                }
                if !status.lastError.isEmpty {
                    Text(status.lastError).font(.caption).foregroundColor(.red).lineLimit(2)
                }
            }
            .padding(10)
            .background(Color.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
            Spacer()
            Button { dismiss() } label: {
                Label("إغلاق", systemImage: "xmark.circle.fill")
                    .padding(10)
                    .background(Color.black.opacity(0.55), in: Capsule())
            }
        }
        .foregroundColor(.white)
    }

    private var bottomBar: some View {
        VStack(spacing: 6) {
            Text("حط الجوال على ستاند قدام التلفزيون، وقرّب لين شاشة التلفزيون تملأ الإطار الأبيض. المربع الأزرق لازم يكون على مكان الترجمة الإنجليزية.")
                .font(.footnote)
                .multilineTextAlignment(.center)
            if reader.maxZoom > 1 {
                HStack {
                    Image(systemName: "minus.magnifyingglass")
                    Slider(value: $zoom, in: 1...reader.maxZoom)
                        .environment(\.layoutDirection, .leftToRight)
                        .onChange(of: zoom) { reader.setZoom($0) }
                    Image(systemName: "plus.magnifyingglass")
                }
                .frame(maxWidth: 420)
            }
        }
        .padding(10)
        .foregroundColor(.white)
        .background(Color.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 12))
    }

    private var blockedMessage: some View {
        VStack(spacing: 12) {
            Text(reader.noCamera ? "ما قدرت أشغّل الكاميرا." : "التطبيق يحتاج إذن الكاميرا عشان يقرأ الترجمة من التلفزيون.")
                .multilineTextAlignment(.center)
            if reader.permissionDenied {
                Button("افتح الإعدادات") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(20)
        .foregroundColor(.white)
        .background(Color.black.opacity(0.8), in: RoundedRectangle(cornerRadius: 14))
    }
}
