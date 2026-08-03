import Foundation
import WatchConnectivity

@MainActor
final class WatchConnection: NSObject, ObservableObject {
    @Published var phoneReachable = false
    @Published var windowsConnected = false

    private var session: WCSession?

    override init() {
        super.init()
        guard WCSession.isSupported() else { return }
        session = .default
        session?.delegate = self
        session?.activate()
    }

    func send(_ command: String, value: Double = 0) {
        guard let session, session.activationState == .activated, session.isReachable else { return }
        session.sendMessage(
            ["command": command, "value": value],
            replyHandler: { [weak self] reply in
                Task { @MainActor in
                    self?.windowsConnected = reply["connected"] as? Bool ?? false
                }
            }
        )
    }
}

extension WatchConnection: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        Task { @MainActor in phoneReachable = session.isReachable }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in phoneReachable = session.isReachable }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        Task { @MainActor in
            windowsConnected = applicationContext["connected"] as? Bool ?? false
        }
    }
}
