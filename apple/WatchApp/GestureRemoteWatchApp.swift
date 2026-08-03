import SwiftUI

@main
struct GestureRemoteWatchApp: App {
    @StateObject private var connection = WatchConnection()
    @StateObject private var gestures = GestureDetector()

    var body: some Scene {
        WindowGroup {
            WatchContentView()
                .environmentObject(connection)
                .environmentObject(gestures)
        }
    }
}
