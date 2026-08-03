import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var bridge: RemoteBridge

    var body: some View {
        NavigationStack {
            Form {
                Section("컴퓨터 연결") {
                    TextField("예: 192.168.0.15", text: $bridge.host)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.numbersAndPunctuation)
                    Button(bridge.isConnected ? "다시 연결" : "연결") {
                        bridge.connect()
                    }
                    Text(bridge.status).font(.caption)
                }

                Section("테스트") {
                    HStack {
                        Button("이전") { bridge.send(command: "previous") }
                        Spacer()
                        Button("재생") { bridge.send(command: "playPause") }
                        Spacer()
                        Button("다음") { bridge.send(command: "next") }
                    }
                    .buttonStyle(.borderless)
                    HStack {
                        Button("축소") { bridge.send(command: "zoomOut") }
                        Spacer()
                        Button("음소거") { bridge.send(command: "mute") }
                        Spacer()
                        Button("확대") { bridge.send(command: "zoomIn") }
                    }
                    .buttonStyle(.borderless)
                }
            }
            .navigationTitle("Gesture Remote")
        }
    }
}
