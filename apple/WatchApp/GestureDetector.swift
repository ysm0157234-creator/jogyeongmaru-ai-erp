import CoreMotion
import Foundation
import WatchKit

@MainActor
final class GestureDetector: ObservableObject {
    @Published var enabled = false
    @Published var lastGesture = "대기 중"

    var onCommand: ((String, Double) -> Void)?

    private let motion = CMMotionManager()
    private let queue = OperationQueue()
    private var lastTrigger = Date.distantPast
    private let threshold = 0.9
    private let scrollThreshold = 0.9
    private let cooldown = 0.2

    init() {
        queue.maxConcurrentOperationCount = 1
        queue.name = "GestureRemote.Motion"
    }

    func toggle() {
        enabled ? stop() : start()
    }

    func start() {
        guard motion.isDeviceMotionAvailable, !motion.isDeviceMotionActive else { return }
        enabled = true
        lastGesture = "제스처 켜짐"
        motion.deviceMotionUpdateInterval = 1.0 / 50.0
        motion.startDeviceMotionUpdates(to: queue) { [weak self] data, _ in
            guard let self, let data else { return }
            let x = data.rotationRate.x
            let y = data.rotationRate.z
            Task { @MainActor in self.process(x: x, y: y) }
        }
    }

    func stop() {
        motion.stopDeviceMotionUpdates()
        enabled = false
        lastGesture = "제스처 꺼짐"
    }

    private func process(x: Double, y: Double) {
        guard enabled, Date().timeIntervalSince(lastTrigger) >= cooldown else { return }
        let command: String

        if abs(x) > scrollThreshold && abs(x) > abs(y) * 2.0 {
            command = "scroll"
        } else if abs(y) > threshold {
            command = y > 0 ? "previous" : "next"
        } else {
            return
        }

        lastTrigger = Date()
        lastGesture = command
        WKInterfaceDevice.current().play(.directionUp)
        onCommand?(command, command == "scroll" ? (y > 0 ? 1 : -1) : 0)
    }
}
