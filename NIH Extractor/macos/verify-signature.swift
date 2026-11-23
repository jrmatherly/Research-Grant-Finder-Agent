import CryptoKit
import Foundation
let a = CommandLine.arguments
let key = try Curve25519.Signing.PublicKey(rawRepresentation: Data(base64Encoded: a[1])!)
let data = try Data(contentsOf: URL(fileURLWithPath: a[3]))
exit(key.isValidSignature(Data(base64Encoded: a[2])!, for: data) ? 0 : 1)
