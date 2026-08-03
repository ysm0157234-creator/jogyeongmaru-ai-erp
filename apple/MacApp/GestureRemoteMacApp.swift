import SwiftUI

@main
struct GestureRemoteMacApp: App {
    @StateObject private var server = MacRemoteServer()

    var body: some Scene {
        MenuBarExtra("Gesture Remote", systemImage: server.isRunning ? "applewatch.radiowaves.left.and.right" : "applewatch.slash") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Gesture Remote")
                    .font(.headline)
                Text(server.status)
                    .font(.caption)
                Text("iPhone에 입력할 주소")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(server.localAddress)
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
                Divider()
                Button("손쉬운 사용 권한 요청") {
                    MacInputController.requestAccessibility()
                }
                Button(server.isRunning ? "서버 다시 시작" : "서버 시작") {
                    server.restart()
                }
                Button("종료") {
                    NSApplication.shared.terminate(nil)
                }
            }
            .padding()
            .frame(width: 280)
        }
    }
}
