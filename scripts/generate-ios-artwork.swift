import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let assets = root.appendingPathComponent("ios/App/App/Assets.xcassets")

func makePNG(size: Int, draw: (CGContext) -> Void) throws -> Data {
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let bytesPerRow = size * 4
    var pixels = Data(count: bytesPerRow * size)

    let image: CGImage? = pixels.withUnsafeMutableBytes { bytes in
        guard let context = CGContext(
            data: bytes.baseAddress,
            width: size,
            height: size,
            bitsPerComponent: 8,
            bytesPerRow: bytesPerRow,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        ) else { return nil }

        context.setAllowsAntialiasing(true)
        context.setShouldAntialias(true)
        draw(context)
        return context.makeImage()
    }

    guard let image else { throw CocoaError(.fileWriteUnknown) }
    let data = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(
        data,
        UTType.png.identifier as CFString,
        1,
        nil
    ) else { throw CocoaError(.fileWriteUnknown) }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
    return data as Data
}

func drawSun(context: CGContext, center: CGPoint, radius: CGFloat, rayInner: CGFloat, rayOuter: CGFloat, lineWidth: CGFloat) {
    context.setStrokeColor(CGColor(gray: 1, alpha: 1))
    context.setLineCap(.round)
    context.setLineJoin(.round)
    context.setLineWidth(lineWidth)
    context.addEllipse(in: CGRect(
        x: center.x - radius,
        y: center.y - radius,
        width: radius * 2,
        height: radius * 2
    ))
    context.strokePath()

    for index in 0..<8 {
        let angle = Double(index) * .pi / 4
        let x = CGFloat(cos(angle))
        let y = CGFloat(sin(angle))
        context.move(to: CGPoint(x: center.x + x * rayInner, y: center.y + y * rayInner))
        context.addLine(to: CGPoint(x: center.x + x * rayOuter, y: center.y + y * rayOuter))
    }
    context.strokePath()
}

let icon = try makePNG(size: 1024) { context in
    context.setFillColor(CGColor(gray: 0.051, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: 1024, height: 1024))
    drawSun(context: context, center: CGPoint(x: 512, y: 512), radius: 142, rayInner: 216, rayOuter: 288, lineWidth: 42)
}

try icon.write(
    to: assets.appendingPathComponent("AppIcon.appiconset/AppIcon-512@2x.png"),
    options: .atomic
)

let splash = try makePNG(size: 2732) { context in
    context.setFillColor(CGColor(gray: 0.035, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: 2732, height: 2732))
    drawSun(context: context, center: CGPoint(x: 1366, y: 1366), radius: 81, rayInner: 123, rayOuter: 169, lineWidth: 24)
}

for name in ["splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"] {
    try splash.write(
        to: assets.appendingPathComponent("Splash.imageset/\(name)"),
        options: .atomic
    )
}

print("Apollo icon and launch artwork generated.")
