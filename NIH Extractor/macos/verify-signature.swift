import CryptoKit
import Foundation
let a = CommandLine.arguments
// Exit 2 for input that cannot be checked, so that only exit 1 means the key rejected the signature.
guard a.count == 4, let rawKey = Data(base64Encoded: a[1]), let signature = Data(base64Encoded: a[2]), let key = try? Curve25519.Signing.PublicKey(rawRepresentation: rawKey), let data = try? Data(contentsOf: URL(fileURLWithPath: a[3])) else {
    FileHandle.standardError.write(Data("verify-signature: needs a base64 public key, a base64 signature and a file that can be read\n".utf8))
    exit(2)
}
exit(key.isValidSignature(signature, for: data) ? 0 : 1)
