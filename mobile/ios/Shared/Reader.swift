import CoreMedia
import CoreVideo
import Foundation
import ImageIO
import Vision

/// Reads the English subtitle from screen frames, translates it and sends the Arabic to the TV.
/// Frames arrive many times a second; at most one is read at a time and the rest are skipped.
final class Reader {
    private let settings: Settings
    private let server: DisplayServer
    private let glossary: Glossary
    private let cache: TranslationCache
    private let deepl: DeepL?
    private let deeplError: String
    private let request = VNRecognizeTextRequest()
    private let work = DispatchQueue(label: "playtranslate.reader", qos: .userInitiated)
    private let lock = NSLock()
    private var busy = false
    private var lastStart: CFAbsoluteTime = 0
    private var pageRequested = false

    // Reader state, only touched on `work`.
    private var candidate = ""
    private var shownSource = ""
    private var showing = false
    private var emptyReads = 0
    private var context = ""
    private var pageUntil: CFAbsoluteTime = 0
    private var lastErrorShown: (String, CFAbsoluteTime) = ("", 0)

    /// Seconds between reads. Vision takes ~0.1-0.3 s per read on recent iPhones.
    var interval: CFAbsoluteTime = 0.3
    var onStatus: ((_ english: String?, _ arabic: String?, _ error: String?, _ ms: Int) -> Void)?

    init(settings: Settings, server: DisplayServer, cache: TranslationCache) {
        self.settings = settings
        self.server = server
        self.cache = cache
        let pack = Pack.load(named: settings.profile.pack)
        var terms = pack.glossary
        for (k, v) in Glossary.parse(userText: settings.userGlossary) { terms[k] = v }
        glossary = Glossary(terms)
        var seeded: [String: String] = [:]
        for (k, v) in pack.translations { seeded[TextProc.cacheKey(k)] = v }
        cache.seed(seeded)
        do {
            deepl = try DeepL(key: settings.deeplKey)
            deeplError = ""
        } catch {
            deepl = nil
            deeplError = (error as? TranslateError)?.message ?? "\(error)"
        }
        request.recognitionLevel = settings.accurateOCR ? .accurate : .fast
        request.recognitionLanguages = ["en-US"]
        request.usesLanguageCorrection = true
    }

    /// Called by the TV ("translate the whole screen once").
    func requestPage() {
        lock.lock(); pageRequested = true; lock.unlock()
    }

    /// A screen-recording frame (ReplayKit), which may carry a rotation.
    func submit(_ sample: CMSampleBuffer) {
        guard let pixels = CMSampleBufferGetImageBuffer(sample) else { return }
        var orientation = CGImagePropertyOrientation.up
        if let raw = CMGetAttachment(sample, key: "RPVideoSampleOrientationKey" as CFString, attachmentModeOut: nil) as? NSNumber,
           let o = CGImagePropertyOrientation(rawValue: raw.uint32Value) {
            orientation = o
        }
        submit(pixels: pixels, orientation: orientation)
    }

    /// A game frame. Frames from the built-in Remote Play stream are upright 16:9 pictures.
    func submit(pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation = .up) {
        let now = CFAbsoluteTimeGetCurrent()
        lock.lock()
        if busy || now - lastStart < interval {
            lock.unlock()
            return
        }
        busy = true
        lastStart = now
        let page = pageRequested
        pageRequested = false
        lock.unlock()

        work.async { [self] in
            autoreleasepool { process(pixels, orientation: orientation, page: page) }
            lock.lock(); busy = false; lock.unlock()
        }
    }

    // MARK: reading

    /// Where the 16:9 game picture sits inside the screen frame (Remote Play letterboxes it).
    static func videoRect(width: Double, height: Double) -> CGRect {
        let aspect = 16.0 / 9.0
        if width / height > aspect {
            let w = height * aspect
            return CGRect(x: (width - w) / 2, y: 0, width: w, height: height)
        }
        let h = width / aspect
        return CGRect(x: 0, y: (height - h) / 2, width: width, height: h)
    }

    /// Vision's region of interest (normalised, bottom-left origin) for a read area
    /// given inside the game picture (top-left origin).
    static func regionOfInterest(area: CGRect, width: Double, height: Double) -> CGRect {
        let video = videoRect(width: width, height: height)
        let x = (video.minX + area.minX * video.width) / width
        let top = (video.minY + area.minY * video.height) / height
        let w = area.width * video.width / width
        let h = area.height * video.height / height
        let roi = CGRect(x: x, y: 1 - top - h, width: w, height: h)
        return roi.intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
    }

    private func readLines(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation, area: CGRect) throws -> [OcrLine] {
        var w = Double(CVPixelBufferGetWidth(pixels))
        var h = Double(CVPixelBufferGetHeight(pixels))
        switch orientation {
        case .left, .right, .leftMirrored, .rightMirrored: swap(&w, &h)
        default: break
        }
        let roi = Reader.regionOfInterest(area: area, width: w, height: h)
        guard !roi.isNull, roi.width > 0.01, roi.height > 0.01 else { return [] }
        request.regionOfInterest = roi
        let handler = VNImageRequestHandler(cvPixelBuffer: pixels, orientation: orientation, options: [:])
        try handler.perform([request])
        let lines: [OcrLine] = (request.results ?? []).compactMap { obs in
            guard let best = obs.topCandidates(1).first, best.confidence >= 0.3 else { return nil }
            let box = obs.boundingBox
            return OcrLine(text: best.string, confidence: best.confidence, top: Double(1 - box.maxY), left: Double(box.minX))
        }
        // Top to bottom; lines on the same row left to right.
        return lines.sorted {
            let ra = Int(($0.top / 0.025).rounded()), rb = Int(($1.top / 0.025).rounded())
            return ra != rb ? ra < rb : $0.left < $1.left
        }
    }

    private func process(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation, page: Bool) {
        let started = CFAbsoluteTimeGetCurrent()
        // A whole-screen translation stays up for a while; subtitles wait.
        if !page && pageUntil > 0 {
            if started < pageUntil { return }
            pageUntil = 0
            server.hide()
            showing = false
            shownSource = ""
        }
        let area = page ? CGRect(x: 0, y: 0, width: 1, height: 1) : settings.effectiveRegion
        let lines: [OcrLine]
        do {
            lines = try readLines(pixels, orientation: orientation, area: area)
        } catch {
            report(nil, nil, "تعذّرت قراءة الشاشة: \(error.localizedDescription)", started)
            return
        }
        if page {
            handlePage(lines, started)
        } else {
            handleSubtitle(lines, started)
        }
    }

    private func handleSubtitle(_ lines: [OcrLine], _ started: CFAbsoluteTime) {
        let segments = TextProc.toSegments(lines)
        let text = TextProc.joined(segments)
        if text.isEmpty {
            emptyReads += 1
            candidate = ""
            // Two empty reads in a row (~0.6 s): the subtitle is gone.
            if showing && emptyReads >= 2 {
                server.hide()
                showing = false
                shownSource = ""
            }
            report(nil, nil, nil, started)
            return
        }
        emptyReads = 0
        if showing && TextProc.similar(text, shownSource) {
            report(nil, nil, nil, started)
            return
        }
        // Wait until the same text is read twice so a line that is still fading in is not sent.
        if !TextProc.similar(text, candidate) {
            candidate = text
            report(text, nil, nil, started)
            return
        }
        do {
            let arabic = try translate(segments)
            server.show(arabic)
            showing = true
            shownSource = text
            context = segments.map(\.text).joined(separator: " ")
            report(text, arabic.map { $0["text"] ?? "" }.joined(separator: "\n"), "", started)
        } catch {
            showError(error, started, english: text)
        }
    }

    private func handlePage(_ lines: [OcrLine], _ started: CFAbsoluteTime) {
        let segments = TextProc.pageSegments(lines)
        guard !segments.isEmpty else {
            report(nil, nil, "ما لقيت نص إنجليزي في الشاشة", started)
            return
        }
        do {
            let arabic = try translate(segments, useContext: false)
            server.show(arabic, mode: "page")
            showing = true
            shownSource = ""
            pageUntil = CFAbsoluteTimeGetCurrent() + 12
            report(TextProc.joined(segments), arabic.map { $0["text"] ?? "" }.joined(separator: "\n"), "", started)
        } catch {
            showError(error, started, english: TextProc.joined(segments))
        }
    }

    private func translate(_ segments: [Segment], useContext: Bool = true) throws -> [[String: String]] {
        var out: [[String: String]] = segments.map {
            ["speaker": $0.speaker.isEmpty ? "" : glossary.translateSpeaker($0.speaker), "text": ""]
        }
        var misses: [Int] = []
        for (i, seg) in segments.enumerated() {
            if let hit = cache.get(TextProc.cacheKey(seg.text)) {
                out[i]["text"] = hit
            } else {
                misses.append(i)
            }
        }
        if !misses.isEmpty {
            guard let deepl else { throw TranslateError.auth(deeplError) }
            let protected = misses.map { glossary.protect(segments[$0].text) }
            let results = try deepl.translate(protected.map(\.0), context: useContext ? context : "")
            for (j, i) in misses.enumerated() {
                let arabic = Glossary.restore(results[j], protected[j].1)
                out[i]["text"] = arabic
                cache.set(TextProc.cacheKey(segments[i].text), arabic)
            }
        }
        return out
    }

    /// Shows a translation problem on the TV too (once every 30 s), since the player is not looking at the phone.
    private func showError(_ error: Error, _ started: CFAbsoluteTime, english: String) {
        let message = (error as? TranslateError)?.message ?? error.localizedDescription
        let now = CFAbsoluteTimeGetCurrent()
        if lastErrorShown.0 != message || now - lastErrorShown.1 > 30 {
            server.show([["speaker": "PlayTranslate", "text": "⚠ " + message]])
            showing = true
            shownSource = ""
            lastErrorShown = (message, now)
        }
        report(english, nil, message, started)
    }

    private func report(_ english: String?, _ arabic: String?, _ error: String?, _ started: CFAbsoluteTime) {
        let ms = Int((CFAbsoluteTimeGetCurrent() - started) * 1000)
        onStatus?(english, arabic, error, ms)
    }
}
