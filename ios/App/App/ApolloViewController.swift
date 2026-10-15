import Capacitor
import UIKit
import WebKit

private final class ApolloWeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    weak var delegate: WKScriptMessageHandler?

    init(delegate: WKScriptMessageHandler) {
        self.delegate = delegate
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        delegate?.userContentController(userContentController, didReceive: message)
    }
}

private final class ApolloRouteViewController: UIViewController {
    let route: String
    var onAppear: ((String) -> Void)?

    init(route: String) {
        self.route = route
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { nil }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        onAppear?(route)
    }
}

final class ApolloTabBarController: UITabBarController, UITabBarControllerDelegate {
    private struct Destination {
        let route: String
        let title: String
    }

    private let destinations = [
        Destination(route: "home", title: "Home"),
        Destination(route: "apollo", title: "Apollo"),
        Destination(route: "music", title: "Music"),
        Destination(route: "calendar", title: "Calendar"),
        Destination(route: "tasks", title: "Tasks"),
        Destination(route: "studio", title: "Studio"),
        Destination(route: "routines", title: "Routines")
    ]

    private let apollo = ApolloViewController()
    private var selectedRoute = "home"
    private var showingMore = false

    override var childForStatusBarStyle: UIViewController? { apollo }
    override var childForStatusBarHidden: UIViewController? { apollo }

    override func viewDidLoad() {
        super.viewDidLoad()
        delegate = self
        let controllers = destinations.enumerated().map { index, destination -> UIViewController in
            let controller = ApolloRouteViewController(route: destination.route)
            controller.view.backgroundColor = .clear
            if index >= 4 {
                controller.onAppear = { [weak self] route in
                    self?.activateOverflowRoute(route)
                }
            }
            controller.tabBarItem = UITabBarItem(
                title: destination.title,
                image: UIImage(named: "Nav-\(destination.route)")?.withRenderingMode(.alwaysTemplate),
                tag: index
            )
            controller.tabBarItem.accessibilityIdentifier = "apollo.tab.\(destination.route)"
            return controller
        }
        setViewControllers(controllers, animated: false)
        customizableViewControllers = []
        selectedIndex = 0

        // A single Capacitor bridge and WKWebView outlive every tab selection.
        // UIKit owns selection and material; the empty route controllers never
        // instantiate duplicate web sessions or interrupt streaming.
        addChild(apollo)
        let content = apollo.view!
        content.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            content.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            content.bottomAnchor.constraint(equalTo: tabBar.topAnchor)
        ])
        apollo.didMove(toParent: self)
        keepNativeBarOnTop()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        keepNativeBarOnTop()
    }

    private func keepNativeBarOnTop() {
        view.bringSubviewToFront(apollo.view)
        view.bringSubviewToFront(tabBar)
    }

    func tabBarController(_ tabBarController: UITabBarController, didSelect viewController: UIViewController) {
        if viewController === moreNavigationController {
            // The system's More list must be tappable; keep the bridge alive
            // but let UIKit present its native overflow UI in front of it.
            apollo.view.isHidden = true
            showingMore = true
            return
        }
        guard let index = viewControllers?.firstIndex(of: viewController), destinations.indices.contains(index) else { return }
        showingMore = false
        apollo.view.isHidden = false
        let route = destinations[index].route
        let reselected = route == selectedRoute
        selectedRoute = route
        apollo.navigate(to: route, reselected: reselected)
        keepNativeBarOnTop()
    }

    func selectRoute(_ route: String) {
        guard let index = destinations.firstIndex(where: { $0.route == route }) else { return }
        if showingMore && route == selectedRoute { return }
        showingMore = false
        selectedRoute = route
        apollo.view.isHidden = false
        if selectedIndex != index { selectedIndex = index }
        keepNativeBarOnTop()
    }

    func setApolloBadge(_ visible: Bool) {
        guard let index = destinations.firstIndex(where: { $0.route == "apollo" }) else { return }
        viewControllers?[index].tabBarItem.badgeValue = visible ? "•" : nil
    }

    private func activateOverflowRoute(_ route: String) {
        guard apollo.view.isHidden || selectedRoute != route else { return }
        showingMore = false
        apollo.view.isHidden = false
        selectedRoute = route
        apollo.navigate(to: route, reselected: false)
        keepNativeBarOnTop()
    }
}

final class ApolloViewController: CAPBridgeViewController, WKScriptMessageHandler {
    private let settingsButton = UIButton(type: .custom)
    private var messageHandler: ApolloWeakScriptMessageHandler?
    private var currentRoute = "home"
    private var bridgeIsReady = false
    private var pendingNavigation: (route: String, reselected: Bool)?

    override func capacitorDidLoad() {
        super.capacitorDidLoad()

        guard
            let publicURL = Bundle.main.resourceURL?.appendingPathComponent("public", isDirectory: true),
            let css = try? String(contentsOf: publicURL.appendingPathComponent("apollo_capacitor.css"), encoding: .utf8),
            let javascript = try? String(contentsOf: publicURL.appendingPathComponent("apollo_capacitor.js"), encoding: .utf8),
            let cssData = try? JSONSerialization.data(withJSONObject: css, options: .fragmentsAllowed),
            let cssLiteral = String(data: cssData, encoding: .utf8)
        else {
            assertionFailure("Apollo's bundled native bridge assets are missing")
            return
        }

        let source = """
        window.__apolloNativeBundledVersion = "1.4";
        (() => {
            if (!document.getElementById("apollo-capacitor-native-css")) {
                const style = document.createElement("style");
                style.id = "apollo-capacitor-native-css";
                style.textContent = \(cssLiteral);
                document.head.appendChild(style);
            }
        })();
        \(javascript)
        """

        let userContentController = webView?.configuration.userContentController
        let handler = ApolloWeakScriptMessageHandler(delegate: self)
        messageHandler = handler
        userContentController?.add(handler, name: "apolloNative")
        userContentController?.addUserScript(
            WKUserScript(
                source: source,
                injectionTime: .atDocumentEnd,
                forMainFrameOnly: true
            )
        )

        webView?.allowsBackForwardNavigationGestures = false
        webView?.scrollView.contentInsetAdjustmentBehavior = .never
        webView?.scrollView.keyboardDismissMode = .interactive
        webView?.allowsLinkPreview = false
    }

    deinit {
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "apolloNative")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        guard let browser = webView else { return }
        let container = UIView(frame: browser.frame)
        container.backgroundColor = UIColor(red: 0.035, green: 0.035, blue: 0.035, alpha: 1)
        view = container
        browser.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(browser)
        let pullToBottom = browser.bottomAnchor.constraint(equalTo: container.safeAreaLayoutGuide.bottomAnchor)
        pullToBottom.priority = .defaultLow
        NSLayoutConstraint.activate([
            browser.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            browser.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            browser.topAnchor.constraint(equalTo: container.topAnchor),
            browser.bottomAnchor.constraint(lessThanOrEqualTo: container.keyboardLayoutGuide.topAnchor),
            pullToBottom
        ])
        configureSettingsButton()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        evaluateJavaScript("window.apolloNativeDidResume?.()")
    }

    func navigate(to route: String, reselected: Bool) {
        webView?.endEditing(true)
        guard bridgeIsReady else {
            pendingNavigation = (route, reselected)
            return
        }
        UISelectionFeedbackGenerator().selectionChanged()
        evaluateJavaScript(
            "window.apolloNativeNavigate?.(\(Self.javaScriptLiteral(route)), \(reselected ? "true" : "false"))"
        )
    }

    private func configureSettingsButton() {
        settingsButton.translatesAutoresizingMaskIntoConstraints = false
        settingsButton.accessibilityLabel = "Settings"
        settingsButton.accessibilityIdentifier = "apollo.settings"
        settingsButton.addTarget(self, action: #selector(settingsTapped), for: .touchUpInside)
        var configuration: UIButton.Configuration
        if #available(iOS 26.0, *) {
            configuration = .glass()
        } else {
            configuration = .gray()
        }
        configuration.image = UIImage(systemName: "gearshape", withConfiguration: UIImage.SymbolConfiguration(pointSize: 17, weight: .medium))
        configuration.baseForegroundColor = .secondaryLabel
        settingsButton.configuration = configuration
        view.addSubview(settingsButton)
        NSLayoutConstraint.activate([
            settingsButton.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            settingsButton.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 6),
            settingsButton.widthAnchor.constraint(equalToConstant: 44),
            settingsButton.heightAnchor.constraint(equalToConstant: 44)
        ])
        view.bringSubviewToFront(settingsButton)
    }

    @objc private func settingsTapped() {
        guard bridgeIsReady else { return }
        webView?.endEditing(true)
        UISelectionFeedbackGenerator().selectionChanged()
        currentRoute = "settings"
        settingsButton.accessibilityTraits = [.button, .selected]
        evaluateJavaScript("window.apolloNativeNavigate?.(\"settings\")")
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard
            message.name == "apolloNative",
            message.frameInfo.isMainFrame,
            let body = message.body as? [String: Any],
            let type = body["type"] as? String
        else { return }

        switch type {
        case "ready":
            bridgeIsReady = true
            if let pendingNavigation {
                self.pendingNavigation = nil
                navigate(to: pendingNavigation.route, reselected: pendingNavigation.reselected)
                break
            }
            if let route = body["route"] as? String {
                currentRoute = route
                settingsButton.accessibilityTraits = route == "settings" ? [.button, .selected] : .button
                (parent as? ApolloTabBarController)?.selectRoute(route)
            }
        case "routeChanged":
            if let route = body["route"] as? String {
                currentRoute = route
                settingsButton.accessibilityTraits = route == "settings" ? [.button, .selected] : .button
                (parent as? ApolloTabBarController)?.selectRoute(route)
            }
        case "themeChanged":
            if let theme = body["theme"] as? String {
                applyTheme(theme, preference: body["preference"] as? String)
            }
        case "badgeChanged":
            (parent as? ApolloTabBarController)?.setApolloBadge(body["visible"] as? Bool ?? false)
        case "confirm":
            presentConfirm(body)
        case "prompt":
            presentPrompt(body)
        case "actionSheet":
            presentActionSheet(body)
        default:
            break
        }
    }

    private func applyTheme(_ theme: String, preference: String?) {
        if preference == "system" {
            overrideUserInterfaceStyle = .unspecified
            parent?.overrideUserInterfaceStyle = .unspecified
            return
        }
        switch theme {
        case "light": overrideUserInterfaceStyle = .light
        case "dark": overrideUserInterfaceStyle = .dark
        default: overrideUserInterfaceStyle = .unspecified
        }
        parent?.overrideUserInterfaceStyle = overrideUserInterfaceStyle
    }
    private func presentConfirm(_ body: [String: Any]) {
        guard let requestID = validatedRequestID(body) else { return }
        let title = validatedText(body["title"], fallback: "Are you sure?", maximumLength: 100)
        let message = validatedText(body["message"], fallback: "", maximumLength: 800)
        let confirmLabel = validatedText(body["confirmLabel"], fallback: "Continue", maximumLength: 40)
        let destructive = body["destructive"] as? Bool ?? true

        let alert = UIAlertController(title: title, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { [weak self] _ in
            self?.resolve(requestID, value: false)
        })
        alert.addAction(UIAlertAction(title: confirmLabel, style: destructive ? .destructive : .default) { [weak self] _ in
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            self?.resolve(requestID, value: true)
        })
        presentSafely(alert, requestID: requestID, cancellationValue: false)
    }
    private func presentPrompt(_ body: [String: Any]) {
        guard let requestID = validatedRequestID(body) else { return }
        let title = validatedText(body["title"], fallback: "Enter a value", maximumLength: 100)
        let message = validatedText(body["message"], fallback: "", maximumLength: 400)
        let initialValue = validatedText(body["value"], fallback: "", maximumLength: 120)
        let confirmLabel = validatedText(body["confirmLabel"], fallback: "Save", maximumLength: 40)

        let alert = UIAlertController(title: title, message: message, preferredStyle: .alert)
        alert.addTextField { field in
            field.text = initialValue
            field.clearButtonMode = .whileEditing
            field.returnKeyType = .done
            field.autocapitalizationType = .sentences
        }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { [weak self] _ in
            self?.resolve(requestID, value: NSNull())
        })
        alert.addAction(UIAlertAction(title: confirmLabel, style: .default) { [weak self, weak alert] _ in
            let value = alert?.textFields?.first?.text?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            self?.resolve(requestID, value: value.isEmpty ? NSNull() : value)
        })
        presentSafely(alert, requestID: requestID, cancellationValue: NSNull())
    }

    private func presentActionSheet(_ body: [String: Any]) {
        guard let requestID = validatedRequestID(body) else { return }
        let title = validatedText(body["title"], fallback: "Choose an option", maximumLength: 100)
        let message = validatedText(body["message"], fallback: "", maximumLength: 400)
        let rawOptions = (body["options"] as? [[String: Any]] ?? []).prefix(8)
        let options = rawOptions.compactMap { option -> (String, String, Bool)? in
            guard let rawID = option["id"] as? String,
                  rawID.range(of: #"^[A-Za-z0-9_.-]{1,64}$"#, options: .regularExpression) != nil else {
                return nil
            }
            let label = validatedText(option["label"], fallback: "", maximumLength: 60)
            guard !label.isEmpty else { return nil }
            return (rawID, label, option["destructive"] as? Bool ?? false)
        }
        guard !options.isEmpty else {
            resolve(requestID, value: NSNull())
            return
        }

        let sheet = UIAlertController(title: title, message: message, preferredStyle: .actionSheet)
        options.forEach { id, label, destructive in
            sheet.addAction(UIAlertAction(title: label, style: destructive ? .destructive : .default) { [weak self] _ in
                self?.resolve(requestID, value: id)
            })
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel) { [weak self] _ in
            self?.resolve(requestID, value: NSNull())
        })
        presentSafely(sheet, requestID: requestID, cancellationValue: NSNull())
    }

    private func presentSafely(_ controller: UIViewController, requestID: String, cancellationValue: Any) {
        guard presentedViewController == nil else {
            resolve(requestID, value: cancellationValue)
            return
        }
        present(controller, animated: !UIAccessibility.isReduceMotionEnabled)
    }

    private func validatedRequestID(_ body: [String: Any]) -> String? {
        guard let requestID = body["requestID"] as? String,
              requestID.range(of: #"^[A-Za-z0-9-]{1,80}$"#, options: .regularExpression) != nil else {
            return nil
        }
        return requestID
    }

    private func validatedText(_ value: Any?, fallback: String, maximumLength: Int) -> String {
        let text = (value as? String ?? fallback).trimmingCharacters(in: .whitespacesAndNewlines)
        return String(text.prefix(maximumLength))
    }

    private func resolve(_ requestID: String, value: Any) {
        guard JSONSerialization.isValidJSONObject(["value": value]),
              let data = try? JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed),
              let encodedValue = String(data: data, encoding: .utf8) else { return }

        evaluateJavaScript(
            "window.__apolloNativeResolve?.(\(Self.javaScriptLiteral(requestID)), \(encodedValue))"
        )
    }

    private func evaluateJavaScript(_ source: String) {
        webView?.evaluateJavaScript(source, completionHandler: nil)
    }

    private static func javaScriptLiteral(_ value: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed),
              let literal = String(data: data, encoding: .utf8) else {
            return "\"\""
        }
        return literal
    }

}
