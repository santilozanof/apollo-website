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

final class ApolloDockController: UIViewController {
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
    private let glass = UIVisualEffectView()
    private let dock = UIView()
    private let row = UIStackView()
    private var buttons: [UIButton] = []
    private var badge = UIView()
    private var leadingConstraint: NSLayoutConstraint?
    private var trailingConstraint: NSLayoutConstraint?
    private var selectedRoute = "home"

    override var childForStatusBarStyle: UIViewController? { apollo }
    override var childForStatusBarHidden: UIViewController? { apollo }

    override func viewDidLoad() {
        super.viewDidLoad()
        UserDefaults.standard.removeObject(forKey: "apollo.setting.accent")
        view.backgroundColor = UIColor { traits in
            traits.userInterfaceStyle == .dark ? .black : UIColor(white: 0.985, alpha: 1)
        }
        // Custom containment is required because UITabBarController replaces
        // destinations five through seven with More on iPhone. The same
        // Capacitor bridge and WKWebView remain mounted for every selection.
        addChild(apollo)
        let content = apollo.view!
        content.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            content.topAnchor.constraint(equalTo: view.topAnchor),
            content.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
        apollo.didMove(toParent: self)
        configureDock()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        let inset: CGFloat = view.bounds.width < 350 ? 6 : 12
        leadingConstraint?.constant = inset
        trailingConstraint?.constant = -inset
        view.bringSubviewToFront(dock)
    }

    private func configureDock() {
        dock.translatesAutoresizingMaskIntoConstraints = false
        dock.accessibilityIdentifier = "apollo.nativeDock"
        glass.translatesAutoresizingMaskIntoConstraints = false
        glass.layer.cornerRadius = 30
        glass.layer.cornerCurve = .continuous
        glass.clipsToBounds = true
        if #available(iOS 26.0, *) {
            let effect = UIGlassEffect(style: .regular)
            effect.isInteractive = true
            glass.effect = effect
        } else {
            glass.effect = UIBlurEffect(style: .systemChromeMaterial)
        }
        dock.addSubview(glass)
        NSLayoutConstraint.activate([
            glass.leadingAnchor.constraint(equalTo: dock.leadingAnchor),
            glass.trailingAnchor.constraint(equalTo: dock.trailingAnchor),
            glass.topAnchor.constraint(equalTo: dock.topAnchor),
            glass.bottomAnchor.constraint(equalTo: dock.bottomAnchor)
        ])

        row.axis = .horizontal
        row.alignment = .fill
        row.distribution = .fillEqually
        row.spacing = 0
        row.translatesAutoresizingMaskIntoConstraints = false
        glass.contentView.addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: glass.contentView.leadingAnchor),
            row.trailingAnchor.constraint(equalTo: glass.contentView.trailingAnchor),
            row.topAnchor.constraint(equalTo: glass.contentView.topAnchor, constant: 4),
            row.bottomAnchor.constraint(equalTo: glass.contentView.bottomAnchor, constant: -4)
        ])

        for (index, destination) in destinations.enumerated() {
            let button = UIButton(type: .custom)
            button.tag = index
            button.accessibilityLabel = destination.title
            button.accessibilityIdentifier = "apollo.tab.\(destination.route)"
            button.setImage(UIImage(named: "Nav-\(destination.route)")?.withRenderingMode(.alwaysTemplate), for: .normal)
            button.imageView?.contentMode = .scaleAspectFit
            button.layer.cornerRadius = 24
            button.layer.cornerCurve = .continuous
            button.addTarget(self, action: #selector(dockTapped(_:)), for: .touchUpInside)
            row.addArrangedSubview(button)
            buttons.append(button)
        }
        badge = UIView()
        badge.translatesAutoresizingMaskIntoConstraints = false
        badge.layer.cornerRadius = 3
        badge.isHidden = true
        badge.isUserInteractionEnabled = false
        buttons[1].addSubview(badge)
        NSLayoutConstraint.activate([
            badge.widthAnchor.constraint(equalToConstant: 6),
            badge.heightAnchor.constraint(equalToConstant: 6),
            badge.centerXAnchor.constraint(equalTo: buttons[1].centerXAnchor, constant: 14),
            badge.centerYAnchor.constraint(equalTo: buttons[1].centerYAnchor, constant: -13)
        ])
        view.addSubview(dock)
        leadingConstraint = dock.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 12)
        trailingConstraint = dock.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -12)
        NSLayoutConstraint.activate([
            leadingConstraint!, trailingConstraint!,
            dock.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -6),
            dock.heightAnchor.constraint(equalToConstant: 58)
        ])
        updateAppearance()
    }

    func selectRoute(_ route: String) {
        guard let index = destinations.firstIndex(where: { $0.route == route }) else { return }
        selectedRoute = route
        for (position, button) in buttons.enumerated() {
            let selected = position == index
            button.accessibilityTraits = selected ? [.button, .selected] : .button
        }
        updateAppearance()
    }

    func setApolloBadge(_ visible: Bool) {
        badge.isHidden = !visible
    }

    private func updateAppearance() {
        let selectedColor: UIColor = .label
        for (index, button) in buttons.enumerated() {
            let selected = destinations[index].route == selectedRoute
            button.tintColor = selected ? selectedColor : .secondaryLabel
            button.backgroundColor = selected ? .tertiarySystemFill : .clear
        }
        badge.backgroundColor = selectedColor
    }

    override func traitCollectionDidChange(_ previousTraitCollection: UITraitCollection?) {
        super.traitCollectionDidChange(previousTraitCollection)
        if previousTraitCollection?.userInterfaceStyle != traitCollection.userInterfaceStyle { updateAppearance() }
    }

    @objc private func dockTapped(_ button: UIButton) {
        guard destinations.indices.contains(button.tag) else { return }
        let route = destinations[button.tag].route
        let reselected = selectedRoute == route
        selectedRoute = route
        selectRoute(route)
        apollo.navigate(to: route, reselected: reselected)
    }
}

final class ApolloViewController: CAPBridgeViewController, WKScriptMessageHandler {
    private let settingsButton = UIButton(type: .custom)
    private var messageHandler: ApolloWeakScriptMessageHandler?
    private var currentRoute = "home"
    private var bridgeIsReady = false
    private var pendingNavigation: (route: String, reselected: Bool)?
    private var keyboardObservers: [NSObjectProtocol] = []

    override func capacitorDidLoad() {
        super.capacitorDidLoad()

        guard
            let publicURL = Bundle.main.resourceURL?.appendingPathComponent("public", isDirectory: true),
            let nativeCSS = try? String(contentsOf: publicURL.appendingPathComponent("apollo_capacitor.css"), encoding: .utf8),
            let dateCSS = try? String(contentsOf: publicURL.appendingPathComponent("apollo_date_nav.css"), encoding: .utf8),
            let oledCSS = try? String(contentsOf: publicURL.appendingPathComponent("apollo_oled.css"), encoding: .utf8),
            let dateJavaScript = try? String(contentsOf: publicURL.appendingPathComponent("apollo_date_nav.js"), encoding: .utf8),
            let javascript = try? String(contentsOf: publicURL.appendingPathComponent("apollo_capacitor.js"), encoding: .utf8),
            let cssData = try? JSONSerialization.data(withJSONObject: nativeCSS + "\n" + dateCSS + "\n" + oledCSS, options: .fragmentsAllowed),
            let cssLiteral = String(data: cssData, encoding: .utf8)
        else {
            assertionFailure("Apollo's bundled native bridge assets are missing")
            return
        }

        let source = """
        window.__apolloNativeBundledVersion = "1.7";
        (() => {
            if (!document.getElementById("apollo-capacitor-native-css")) {
                const style = document.createElement("style");
                style.id = "apollo-capacitor-native-css";
                style.textContent = \(cssLiteral);
                document.head.appendChild(style);
            }
        })();
        \(dateJavaScript)
        \(javascript)
        """

        let userContentController = webView?.configuration.userContentController
        let handler = ApolloWeakScriptMessageHandler(delegate: self)
        messageHandler = handler
        userContentController?.add(handler, name: "apolloNative")
        // Prevent a deployed 1.6 page from installing its older bridge before
        // the signed 1.7 bundle takes ownership of native listeners/dialogs.
        userContentController?.addUserScript(
            WKUserScript(
                source: "window.__apolloCapacitorVersion = '1.6';",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
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
        webView?.isOpaque = false
        webView?.backgroundColor = .clear
        webView?.scrollView.backgroundColor = .clear
    }

    deinit {
        keyboardObservers.forEach(NotificationCenter.default.removeObserver)
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "apolloNative")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        guard let browser = webView else { return }
        let container = UIView(frame: browser.frame)
        container.backgroundColor = .clear
        view = container
        browser.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(browser)
        if #available(iOS 17.0, *) {
            container.keyboardLayoutGuide.usesBottomSafeArea = false
        }
        let pullToBottom = browser.bottomAnchor.constraint(equalTo: container.bottomAnchor)
        pullToBottom.priority = .defaultLow
        NSLayoutConstraint.activate([
            browser.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            browser.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            browser.topAnchor.constraint(equalTo: container.topAnchor),
            browser.bottomAnchor.constraint(lessThanOrEqualTo: container.keyboardLayoutGuide.topAnchor),
            pullToBottom
        ])
        // Keep the composer anchored through a Send tap. Focus can leave the
        // textarea before UIKit finishes hiding the keyboard; focus-within is
        // therefore not a reliable keyboard-layout signal.
        keyboardObservers = [
            NotificationCenter.default.addObserver(
                forName: UIResponder.keyboardWillShowNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in self?.setKeyboardVisible(true) },
            NotificationCenter.default.addObserver(
                forName: UIResponder.keyboardDidHideNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in self?.setKeyboardVisible(false) }
        ]
        configureSettingsButton()
    }

    private func setKeyboardVisible(_ visible: Bool) {
        evaluateJavaScript("window.apolloNativeKeyboardChanged?.(\(visible ? "true" : "false"))")
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        evaluateJavaScript("window.apolloNativeDidResume?.()")
    }

    func navigate(to route: String, reselected: Bool) {
        webView?.endEditing(true)
        setCurrentRoute(route)
        guard bridgeIsReady else {
            pendingNavigation = (route, reselected)
            return
        }
        UISelectionFeedbackGenerator().selectionChanged()
        evaluateJavaScript(
            "window.apolloNativeNavigate?.(\(Self.javaScriptLiteral(route)), \(reselected ? "true" : "false"))"
        )
    }

    private func setCurrentRoute(_ route: String) {
        currentRoute = route
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
        configuration.baseForegroundColor = .label
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
        settingsButton.accessibilityTraits = [.button, .selected]
        navigate(to: "settings", reselected: false)
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
                setCurrentRoute(route)
                settingsButton.accessibilityTraits = route == "settings" ? [.button, .selected] : .button
                (parent as? ApolloDockController)?.selectRoute(route)
            }
        case "routeChanged":
            if let route = body["route"] as? String {
                setCurrentRoute(route)
                settingsButton.accessibilityTraits = route == "settings" ? [.button, .selected] : .button
                (parent as? ApolloDockController)?.selectRoute(route)
            }
        case "themeChanged":
            if let theme = body["theme"] as? String {
                applyTheme(theme, preference: body["preference"] as? String)
            }
        case "badgeChanged":
            (parent as? ApolloDockController)?.setApolloBadge(body["visible"] as? Bool ?? false)
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
