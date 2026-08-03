import SwiftUI

@main
struct GestureRemoteApp: App {
    @StateObject private var bridge = RemoteBridge()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(bridge)
        }
    }
}
