import ReplayKit

/// The screen-sharing extension. iOS runs it while "PlayTranslate" screen broadcast is on,
/// so it keeps working while PS Remote Play is in front.
final class SampleHandler: RPBroadcastSampleHandler {
    private var session: Session?

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        let settings = Settings.load()
        let session = Session(settings: settings)
        session.onFatal = { [weak self] why in
            self?.finishBroadcastWithError(NSError(domain: "PlayTranslate", code: 1,
                                                   userInfo: [NSLocalizedDescriptionKey: why]))
        }
        session.start()
        self.session = session
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        session?.handle(sampleBuffer)
    }

    override func broadcastFinished() {
        session?.stop()
        session = nil
    }
}
