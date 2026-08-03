import SwiftUI

struct WatchContentView: View {
    @EnvironmentObject private var connection: WatchConnection
    @EnvironmentObject private var gestures: GestureDetector
    @State private var crownValue = 0.0
    @State private var lastCrownValue = 0.0

    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                Text(connection.windowsConnected ? "● Windows 연결됨" : "○ 연결 대기")
                    .font(.caption2)
                    .foregroundStyle(connection.windowsConnected ? .green : .secondary)

                Button(gestures.enabled ? "제스처 끄기" : "제스처 켜기") {
                    gestures.toggle()
                }
                .buttonStyle(.borderedProminent)

                HStack {
                    Button("◀︎") { connection.send("previous") }
                        .accessibilityLabel("이전")
                    Button("▶︎") { connection.send("next") }
                        .accessibilityLabel("다음")
                }

                HStack {
                    Button("−") { connection.send("zoomOut") }
                        .accessibilityLabel("축소")
                    Button("+") { connection.send("zoomIn") }
                        .accessibilityLabel("확대")
                }

                Button("재생 / 일시정지") { connection.send("playPause") }
                Text(gestures.lastGesture).font(.caption2)
            }
        }
        .focusable()
        .digitalCrownRotation(
            $crownValue,
            from: -100,
            through: 100,
            by: 1,
            sensitivity: .medium,
            isContinuous: true,
            isHapticFeedbackEnabled: true
        )
        .onChange(of: crownValue) { _, newValue in
            let delta = newValue - lastCrownValue
            guard abs(delta) >= 1 else { return }
            connection.send(delta > 0 ? "volumeUp" : "volumeDown")
            lastCrownValue = newValue
        }
        .onAppear {
            gestures.onCommand = { command, value in
                connection.send(command, value: value)
            }
        }
    }
}
