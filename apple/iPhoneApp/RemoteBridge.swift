import Foundation
import WatchConnectivity

@MainActor
final class RemoteBridge: NSObject, ObservableObject {
    @Published var host = UserDefaults.standard.string(forKey: "windowsHost") ?? ""
    @Published var isConnected = false
    @Published var status = "컴퓨터 주소를 입력하세요"

    private var socket: URLSessionWebSocketTask?
    private var watchSession: WCSession?

    override init() {
        super.init()
        if WCSession.isSupported() {
            watchSession = .default
            watchSession?.delegate = self
            watchSession?.activate()
        }
    }

    func connect() {
        disconnect()
        let trimmed = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: "ws://\(trimmed):8765/ws") else {
            status = "주소 형식이 잘못되었습니다"
            return
        }
        UserDefaults.standard.set(trimmed, forKey: "windowsHost")
        socket = URLSession.shared.webSocketTask(with: url)
        socket?.resume()
        status = "연결 시도 중: \(trimmed)"
        receive()
        send(command: "ping", value: 0, silent: true)
    }

    func disconnect() {
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
        isConnected = false
        updateWatchStatus()
    }

    func send(command: String, value: Double = 0, silent: Bool = false) {
        guard let socket else {
            if !silent { status = "컴퓨터에 먼저 연결하세요" }
            return
        }
        let payload: [String: Any] = ["command": command, "value": value]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else { return }
        socket.send(.string(text)) { [weak self] error in
            Task { @MainActor in
                if let error {
                    self?.isConnected = false
                    self?.status = "전송 실패: \(error.localizedDescription)"
                    self?.updateWatchStatus()
                } else if !silent {
                    self?.status = "전송: \(command)"
                }
            }
        }
    }

    private func receive() {
        socket?.receive { [weak self] result in
            Task { @MainActor in
                switch result {
                case .success:
                    self?.isConnected = true
                    self?.status = "컴퓨터 연결됨"
                    self?.updateWatchStatus()
                    self?.receive()
                case .failure(let error):
                    self?.isConnected = false
                    self?.status = "연결 끊김: \(error.localizedDescription)"
                    self?.updateWatchStatus()
                }
            }
        }
    }

    private func updateWatchStatus() {
        try? watchSession?.updateApplicationContext(["connected": isConnected])
    }
}

extension RemoteBridge: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {}

    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) { session.activate() }

    nonisolated func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        let command = message["command"] as? String
        let value = message["value"] as? Double ?? 0
        Task { @MainActor in
            if let command { send(command: command, value: value) }
            replyHandler(["connected": isConnected])
        }
    }
}
