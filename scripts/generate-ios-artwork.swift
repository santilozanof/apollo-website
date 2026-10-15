import AppKit
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let assets = root.appendingPathComponent("ios/App/App/Assets.xcassets")

func rasterizeSVG(_ svg: Data, size: Int, background: CGColor? = nil, artwork: CGRect? = nil) throws -> Data {
    guard let image = NSImage(data: svg) else { throw CocoaError(.fileReadCorruptFile) }
    var pixels = Data(count: size * size * 4)
    let output: CGImage? = pixels.withUnsafeMutableBytes { bytes in
        guard let context = CGContext(
            data: bytes.baseAddress,
            width: size,
            height: size,
            bitsPerComponent: 8,
            bytesPerRow: size * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }
        context.setAllowsAntialiasing(true)
        context.setShouldAntialias(true)
        context.interpolationQuality = .high
        if let background {
            context.setFillColor(background)
            context.fill(CGRect(x: 0, y: 0, width: size, height: size))
        } else {
            context.clear(CGRect(x: 0, y: 0, width: size, height: size))
        }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        image.draw(in: artwork ?? CGRect(x: 0, y: 0, width: size, height: size), from: .zero, operation: .sourceOver, fraction: 1)
        NSGraphicsContext.restoreGraphicsState()
        return context.makeImage()
    }
    guard let output else { throw CocoaError(.fileWriteUnknown) }
    let result = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(result, UTType.png.identifier as CFString, 1, nil) else {
        throw CocoaError(.fileWriteUnknown)
    }
    CGImageDestinationAddImage(destination, output, nil)
    guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
    return result as Data
}

// The original Apollo favicon artwork predates the sun-icon experiment.
let originalA = try Data(contentsOf: root.appendingPathComponent("ios/Artwork/apollo-original-a.svg"))
let icon = try rasterizeSVG(originalA, size: 1024)
try icon.write(to: assets.appendingPathComponent("AppIcon.appiconset/AppIcon-512@2x.png"), options: .atomic)

let splash = try rasterizeSVG(
    originalA,
    size: 2732,
    background: CGColor(gray: 0.035, alpha: 1),
    artwork: CGRect(x: 1174, y: 1174, width: 384, height: 384)
)
for name in ["splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"] {
    try splash.write(to: assets.appendingPathComponent("Splash.imageset/\(name)"), options: .atomic)
}

// Extract the exact desktop navigation paths, rather than substituting SF Symbols.
let desktop = try String(contentsOf: root.appendingPathComponent("index.html"), encoding: .utf8)
let routines = try String(contentsOf: root.appendingPathComponent("routines.js"), encoding: .utf8)
let pattern = #"(?s)<span class="nav-icon[^"]*">\s*(<svg[^>]*>.*?</svg>)\s*</span>\s*<span class="nav-label">(Home|Apollo|Music|Calendar|Tasks|Studio)</span>"#
let regex = try NSRegularExpression(pattern: pattern)
let matches = regex.matches(in: desktop, range: NSRange(desktop.startIndex..., in: desktop))
var artwork: [String: String] = [:]
for match in matches {
    guard let svgRange = Range(match.range(at: 1), in: desktop),
          let titleRange = Range(match.range(at: 2), in: desktop) else { continue }
    artwork[String(desktop[titleRange]).lowercased()] = String(desktop[svgRange])
}
let routinePattern = #"(?s)<span class="nav-icon">\s*(<svg[^>]*>.*?</svg>)\s*</span>\s*<span class="nav-label">Routines</span>"#
let routineRegex = try NSRegularExpression(pattern: routinePattern)
if let match = routineRegex.firstMatch(in: routines, range: NSRange(routines.startIndex..., in: routines)),
   let range = Range(match.range(at: 1), in: routines) {
    artwork["routines"] = String(routines[range])
}
for route in ["home", "apollo", "music", "calendar", "tasks", "studio", "routines"] {
    guard let source = artwork[route] else { throw CocoaError(.fileReadCorruptFile) }
    let svg = source.replacingOccurrences(
        of: "<svg ",
        with: "<svg xmlns=\"http://www.w3.org/2000/svg\" fill=\"none\" stroke=\"#ffffff\" stroke-width=\"1.7\" stroke-linecap=\"round\" stroke-linejoin=\"round\" "
    )
    let folder = assets.appendingPathComponent("Nav-\(route).imageset")
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    try rasterizeSVG(Data(svg.utf8), size: 72).write(to: folder.appendingPathComponent("Nav-\(route)@3x.png"), options: .atomic)
    let catalog = """
    {"images":[{"filename":"Nav-\(route)@3x.png","idiom":"universal","scale":"3x"}],"info":{"author":"xcode","version":1},"properties":{"template-rendering-intent":"template"}}
    """
    try catalog.write(to: folder.appendingPathComponent("Contents.json"), atomically: true, encoding: .utf8)
}
print("Restored original A app artwork and generated seven desktop-matched native tab icons.")
