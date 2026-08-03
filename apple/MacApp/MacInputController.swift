import AppKit
import ApplicationServices

enum MacInputController {
    static func requestAccessibility() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }

    static func execute(command: String, value: Double) {
        switch command {
        case "next": key(124)
        case "previous": key(123)
        case "up": key(126)
        case "down": key(125)
        case "scroll": scroll(lines: Int32(value * 3))
        case "zoomIn": chord(keyCode: 24, flags: .maskCommand)
        case "zoomOut": chord(keyCode: 27, flags: .maskCommand)
        case "volumeUp": changeVolume(by: 6)
        case "volumeDown": changeVolume(by: -6)
        case "mute": toggleMute()
        case "playPause": key(49)
        case "space": key(49)
        case "ping": break
        default: break
        }
    }

    private static func key(_ code: CGKeyCode) {
        let source = CGEventSource(stateID: .hidSystemState)
        CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
        CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
    }

    private static func chord(keyCode: CGKeyCode, flags: CGEventFlags) {
        let source = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: true)
        down?.flags = flags
        down?.post(tap: .cghidEventTap)
        let up = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: false)
        up?.flags = flags
        up?.post(tap: .cghidEventTap)
    }

    private static func scroll(lines: Int32) {
        CGEvent(
            scrollWheelEvent2Source: nil,
            units: .line,
            wheelCount: 1,
            wheel1: lines,
            wheel2: 0,
            wheel3: 0
        )?.post(tap: .cghidEventTap)
    }

    private static func changeVolume(by amount: Int) {
        runAppleScript("""
        set currentVolume to output volume of (get volume settings)
        set volume output volume (currentVolume + \(amount))
        """)
    }

    private static func toggleMute() {
        runAppleScript("""
        set currentMute to output muted of (get volume settings)
        set volume output muted (not currentMute)
        """)
    }

    private static func runAppleScript(_ source: String) {
        NSAppleScript(source: source)?.executeAndReturnError(nil)
    }
}
