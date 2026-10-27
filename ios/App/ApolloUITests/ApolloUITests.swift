import XCTest

final class ApolloUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func dockButton(_ route: String, in app: XCUIApplication) -> XCUIElement {
        app.buttons["apollo.tab.\(route)"]
    }

    private func keepScreenshot(_ name: String, in app: XCUIApplication) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testSevenDirectDestinationsAndSettings() throws {
        let app = XCUIApplication()
        app.launch()
        let routes = ["home", "apollo", "music", "calendar", "tasks", "studio", "routines"]
        for route in routes {
            XCTAssertTrue(dockButton(route, in: app).waitForExistence(timeout: 20), "Missing direct \(route) destination")
        }
        XCTAssertFalse(app.buttons["More"].exists)
        keepScreenshot("Seven-destination native glass dock", in: app)
        for route in routes {
            let button = dockButton(route, in: app)
            XCTAssertTrue(button.isHittable, "\(route) must be tappable")
            button.tap()
            XCTAssertTrue(button.isSelected, "\(route) must have a selected state")
            if route == "studio" { keepScreenshot("Direct Studio route", in: app) }
        }
        let settings = app.buttons["apollo.settings"]
        XCTAssertTrue(settings.isHittable)
        settings.tap()
        XCTAssertTrue(settings.isSelected)
        keepScreenshot("Settings native chrome", in: app)
    }

    func testChatDraftSurvivesKeyboardAndTabSwitches() throws {
        let app = XCUIApplication()
        app.launch()
        dockButton("apollo", in: app).tap()
        let input = app.textViews["Talk to Apollo..."]
        guard input.waitForExistence(timeout: 12) else {
            throw XCTSkip("Private Apollo server is unavailable in this simulator session")
        }
        input.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        input.typeText("iOS simulator draft\nSecond line\nThird line")
        XCTAssertTrue((input.value as? String ?? "").contains("Third line"))
        keepScreenshot("Chat draft and software keyboard", in: app)
        let outside = app.webViews.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.25))
        for _ in 0..<3 {
            outside.tap()
            XCTAssertFalse(app.keyboards.firstMatch.exists)
            input.tap()
            XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
            XCTAssertTrue((input.value as? String ?? "").contains("Third line"))
        }
        outside.tap()
        dockButton("music", in: app).tap()
        dockButton("calendar", in: app).tap()
        dockButton("apollo", in: app).tap()
        XCTAssertTrue((input.value as? String ?? "").contains("Third line"), "WebView must remain mounted")
    }

    func testMusicQueueSecondaryAction() throws {
        let app = XCUIApplication()
        app.launch()
        dockButton("music", in: app).tap()
        let queue = app.buttons["Open Spotify queue"]
        guard queue.waitForExistence(timeout: 12) else {
            throw XCTSkip("Private Apollo server is unavailable in this simulator session")
        }
        queue.tap()
        let close = app.buttons["Close queue"]
        XCTAssertTrue(close.waitForExistence(timeout: 10))
        XCTAssertTrue(close.isHittable)
        keepScreenshot("Music queue sheet", in: app)
        close.tap()
    }

    func testStudioScrollEdgeKeepsDockAndContentUsable() throws {
        let app = XCUIApplication()
        app.launch()
        dockButton("studio", in: app).tap()
        guard app.staticTexts["Studio"].waitForExistence(timeout: 12) else {
            throw XCTSkip("Private Apollo server is unavailable in this simulator session")
        }
        let page = app.webViews.firstMatch
        for _ in 0..<5 { page.swipeUp() }
        XCTAssertTrue(dockButton("studio", in: app).isHittable)
        keepScreenshot("Studio scroll edge beneath glass", in: app)
    }

    func testCalendarAndRoutinesShareDateControlGeometry() throws {
        let app = XCUIApplication()
        app.launch()
        dockButton("calendar", in: app).tap()
        let calendar = ["Add event", "Today", "Previous day", "Next day"]
            .map { app.buttons[$0] }
        guard calendar.allSatisfy({ $0.waitForExistence(timeout: 12) }) else {
            throw XCTSkip("Private Apollo calendar page is unavailable in this simulator session")
        }
        let calendarFrames = calendar.map(\.frame)
        keepScreenshot("Calendar shared date navigation", in: app)

        dockButton("routines", in: app).tap()
        let routines = ["New routine", "Today", "Previous day", "Next day"]
            .map { app.buttons[$0] }
        guard routines.allSatisfy({ $0.waitForExistence(timeout: 12) }) else {
            throw XCTSkip("Private Apollo routines page is unavailable in this simulator session")
        }
        for (calendarFrame, routine) in zip(calendarFrames, routines) {
            XCTAssertEqual(calendarFrame.minX, routine.frame.minX, accuracy: 1.5)
            XCTAssertEqual(calendarFrame.width, routine.frame.width, accuracy: 1.5)
            XCTAssertGreaterThanOrEqual(routine.frame.height, 42)
        }
        keepScreenshot("Routines shared date navigation", in: app)
    }

    func testSettingsUseMonochromeWithoutAccentControl() throws {
        let app = XCUIApplication()
        app.launch()
        app.buttons["apollo.settings"].tap()
        guard app.staticTexts["Settings"].waitForExistence(timeout: 12) else {
            throw XCTSkip("Private Apollo server is unavailable in this simulator session")
        }
        XCTAssertFalse(app.staticTexts["Accent Color"].exists)
        keepScreenshot("Monochrome Settings", in: app)
    }
}
