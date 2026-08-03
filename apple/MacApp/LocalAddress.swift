import Foundation

enum LocalAddress {
    static func wifiIPv4() -> String {
        var result = "Mac의 Wi-Fi IP"
        var pointer: UnsafeMutablePointer<ifaddrs>?

        guard getifaddrs(&pointer) == 0, let first = pointer else { return result }
        defer { freeifaddrs(pointer) }

        for interface in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let family = interface.pointee.ifa_addr.pointee.sa_family
            guard family == UInt8(AF_INET) else { continue }
            let name = String(cString: interface.pointee.ifa_name)
            guard name == "en0" || name == "en1" else { continue }

            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(
                interface.pointee.ifa_addr,
                socklen_t(interface.pointee.ifa_addr.pointee.sa_len),
                &hostname,
                socklen_t(hostname.count),
                nil,
                0,
                NI_NUMERICHOST
            ) == 0 {
                result = String(cString: hostname)
                break
            }
        }
        return result
    }
}
