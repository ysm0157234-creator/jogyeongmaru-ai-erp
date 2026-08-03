import Foundation
import Network

@MainActor
final class MacRemoteServer: ObservableObject {
    @Published var isRunning = false
    @Published var status = "시작 중"
    @Published var localAddress = "\(LocalAddress.wifiIPv4()):8765"

    private var listener: NWListener?
    private var connections: [NWConnection] = []

    init() {
        start()
        MacInputController.requestAccessibility()
    }

    func restart() {
        listener?.cancel()
        connections.forEach { $0.cancel() }
        connections.removeAll()
        start()
    }

    private func start() {
        do {
            let websocket = NWProtocolWebSocket.Options()
            websocket.autoReplyPing = true
            let parameters = NWParameters.tcp
            parameters.defaultProtocolStack.applicationProtocols.insert(websocket, at: 0)

            let listener = try NWListener(using: parameters, on: 8765)
            self.listener = listener
            listener.stateUpdateHandler = { [weak self] state in
                Task { @MainActor in
                    guard let self else { return }
                    switch state {
                    case .ready:
                        self.isRunning = true
                        self.status = "연결 대기 중 · 포트 8765"
                        self.localAddress = "\(LocalAddress.wifiIPv4()):8765"
                    case .failed(let error):
                        self.isRunning = false
                        self.status = "서버 오류: \(error.localizedDescription)"
                    case .cancelled:
                        self.isRunning = false
                    default:
                        break
                    }
                }
            }
            listener.newConnectionHandler = { [weak self] connection in
                Task { @MainActor in self?.accept(connection) }
            }
            listener.start(queue: .global(qos: .userInitiated))
        } catch {
            status = "서버 시작 실패: \(error.localizedDescription)"
        }
    }

    private func accept(_ connection: NWConnection) {
        connections.append(connection)
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            Task { @MainActor in
                guard let self, let connection else { return }
                switch state {
                case .ready:
                    self.status = "iPhone 연결됨"
                    self.receive(on: connection)
                case .failed, .cancelled:
                    self.connections.removeAll { $0 === connection }
                    self.status = "연결 대기 중 · 포트 8765"
                default:
                    break
                }
            }
        }
        connection.start(queue: .global(qos: .userInitiated))
    }

    private func receive(on connection: NWConnection) {
        connection.receiveMessage { [weak self, weak connection] content, _, _, error in
            guard let self, let connection else { return }
            if let content,
               let message = try? JSONDecoder().decode(RemoteMessage.self, from: content) {
                Task { @MainActor in
                    MacInputController.execute(command: message.command, value: message.value)
                    self.sendAcknowledgement(on: connection)
                }
            }

            if error == nil {
                Task { @MainActor in self.receive(on: connection) }
            }
        }
    }

    private func sendAcknowledgement(on connection: NWConnection) {
        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "ack", metadata: [metadata])
        connection.send(
            content: Data(#"{"ok":true}"#.utf8),
            contentContext: context,
            isComplete: true,
            completion: .contentProcessed { _ in }
        )
    }
}

private struct RemoteMessage: Decodable {
    let command: String
    let value: Double
}
