import XCTest

final class ApolloUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testNativeTabsPreserveOneWebSession() throws {
        let app = XCUIApplication()
        app.launch()
        let tabs = app.tabBars.firstMatch
        XCTAssertTrue(tabs.waitForExistence(timeout: 20), "UIKit tab bar should be present")

        let apollo = tabs.buttons["Apollo"]
        XCTAssertTrue(apollo.exists)
        apollo.tap()
        XCTAssertTrue(app.textViews["Talk to Apollo..."].waitForExistence(timeout: 15))
        let input = app.textViews["Talk to Apollo..."]
        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "Software keyboard must open")
        XCTAssertTrue(app.keyboards.firstMatch.isHittable, "Software keyboard must be visible")
        input.typeText("iOS simulator draft\nSecond line\nThird line")
        XCTAssertTrue((input.value as? String ?? "").contains("Third line"))
        add(XCTAttachment(screenshot: app.screenshot()))

        // Dismiss and immediately reopen without sending anything or altering
        // account data. The same DOM textarea must retain its unsent draft.
        let outside = app.webViews.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.25))
        for _ in 0..<3 {
            outside.tap()
            XCTAssertFalse(app.keyboards.firstMatch.exists, "Outside tap must dismiss the software keyboard")
            input.tap()
            XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "Rapid refocus must reopen the software keyboard")
            XCTAssertTrue(app.keyboards.firstMatch.isHittable, "Reopened keyboard must be visible")
            XCTAssertTrue((input.value as? String ?? "").contains("Third line"))
        }
        let keyboardOpen = XCTAttachment(screenshot: app.screenshot())
        keyboardOpen.name = "Chat draft with keyboard open"
        keyboardOpen.lifetime = .keepAlways
        add(keyboardOpen)

        // The stock iOS tab bar is covered by the keyboard. Dismiss before
        // changing tabs, as in other system tab-bar apps.
        outside.tap()
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        tabs.buttons["Music"].tap()
        XCTAssertTrue(tabs.buttons["Music"].isSelected)
        tabs.buttons["Calendar"].tap()
        XCTAssertTrue(tabs.buttons["Calendar"].isSelected)
        tabs.buttons["Apollo"].tap()
        XCTAssertTrue((input.value as? String ?? "").contains("Third line"), "Tab switching must not reload the WebView")
    }

    func testNativeMoreKeepsStudioAccessible() throws {
        let app = XCUIApplication()
        app.launch()
        let more = app.tabBars.buttons["More"]
        XCTAssertTrue(more.waitForExistence(timeout: 20))
        more.tap()
        let moreShot = XCTAttachment(screenshot: app.screenshot())
        moreShot.name = "Native More list"
        moreShot.lifetime = .keepAlways
        add(moreShot)
        let studio = app.staticTexts["Studio"].firstMatch
        XCTAssertTrue(studio.waitForExistence(timeout: 10), "Studio must appear in native More")
        studio.tap()
        XCTAssertTrue(app.staticTexts["Studio"].waitForExistence(timeout: 10))
        let settings = app.buttons["apollo.settings"]
        XCTAssertTrue(settings.isHittable, "Settings remains accessible")
        settings.tap()
        XCTAssertTrue(app.staticTexts["Settings"].waitForExistence(timeout: 10))
    }

    func testMusicQueueIsIndependentSecondaryAction() throws {
        let app = XCUIApplication()
        app.launch()
        let music = app.tabBars.buttons["Music"]
        XCTAssertTrue(music.waitForExistence(timeout: 20))
        music.tap()
        let queue = app.buttons["Open Spotify queue"]
        XCTAssertTrue(queue.waitForExistence(timeout: 15), "Queue must remain independently accessible")
        queue.tap()
        let close = app.buttons["Close queue"]
        XCTAssertTrue(close.waitForExistence(timeout: 10), "The queue sheet must open above Music")
        XCTAssertTrue(close.isHittable, "The queue sheet must not be hidden behind its scrim")
        let queueShot = XCTAttachment(screenshot: app.screenshot())
        queueShot.name = "Music queue sheet"
        queueShot.lifetime = .keepAlways
        add(queueShot)
        close.tap()
    }
}
