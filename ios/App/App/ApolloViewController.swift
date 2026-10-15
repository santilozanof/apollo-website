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

final class ApolloViewController: CAPBridgeViewController, WKScriptMessageHandler {
    private struct Destination {
        let route: String
        let title: String
        let symbol: String
    }

    private struct DockItem {
        let button: UIButton
        let selection: UIView
        let icon: UIImageView
        let badge: UIView
    }

    private let destinations = [
        Destination(route: "home", title: "Home", symbol: "house"),
        Destination(route: "apollo", title: "Apollo", symbol: "sun.max"),
        Destination(route: "music", title: "Music", symbol: "music.note"),
        Destination(route: "calendar", title: "Calendar", symbol: "calendar"),
        Destination(route: "tasks", title: "Tasks", symbol: "checkmark.circle"),
        Destination(route: "studio", title: "Studio", symbol: "waveform"),
        Destination(route: "routines", title: "Routines", symbol: "repeat"),
        Destination(route: "settings", title: "Settings", symbol: "gearshape")
    ]

    private let dock = UIView(frame: .zero)
    private var dockHeightConstraint: NSLayoutConstraint?
    private var dockItems: [DockItem] = []
    private var messageHandler: ApolloWeakScriptMessageHandler?
    private var keyboardObservers: [NSObjectProtocol] = []
    private var currentRoute = "home"
    private var bridgeIsReady = false

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
        window.__apolloNativeBundledVersion = "1.2";
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

        configureDock()
        observeKeyboard()
    }

    deinit {
        keyboardObservers.forEach(NotificationCenter.default.removeObserver)
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: "apolloNative")
    }

    override func viewSafeAreaInsetsDidChange() {
        super.viewSafeAreaInsetsDidChange()
        dockHeightConstraint?.constant = 58 + view.safeAreaInsets.bottom
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        evaluateJavaScript("window.apolloNativeDidResume?.()")
    }

    private func configureDock() {
        guard dock.superview == nil else { return }

        dock.translatesAutoresizingMaskIntoConstraints = false
        dock.accessibilityIdentifier = "apollo.nativeDock"

        let material = UIVisualEffectView(effect: UIBlurEffect(style: .systemChromeMaterial))
        material.translatesAutoresizingMaskIntoConstraints = false
        dock.addSubview(material)
        NSLayoutConstraint.activate([
            material.leadingAnchor.constraint(equalTo: dock.leadingAnchor),
            material.trailingAnchor.constraint(equalTo: dock.trailingAnchor),
            material.topAnchor.constraint(equalTo: dock.topAnchor),
            material.bottomAnchor.constraint(equalTo: dock.bottomAnchor)
        ])

        let separator = UIView(frame: .zero)
        separator.backgroundColor = UIColor.separator.withAlphaComponent(0.25)
        separator.translatesAutoresizingMaskIntoConstraints = false
        dock.addSubview(separator)
        NSLayoutConstraint.activate([
            separator.leadingAnchor.constraint(equalTo: dock.leadingAnchor),
            separator.trailingAnchor.constraint(equalTo: dock.trailingAnchor),
            separator.topAnchor.constraint(equalTo: dock.topAnchor),
            separator.heightAnchor.constraint(equalToConstant: 0.5)
        ])

        let row = UIStackView(frame: .zero)
        row.axis = .horizontal
        row.alignment = .fill
        row.distribution = .fillEqually
        row.spacing = 0
        row.translatesAutoresizingMaskIntoConstraints = false
        dock.addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: dock.leadingAnchor, constant: 4),
            row.trailingAnchor.constraint(equalTo: dock.trailingAnchor, constant: -4),
            row.topAnchor.constraint(equalTo: dock.topAnchor, constant: 5),
            row.heightAnchor.constraint(equalToConstant: 49)
        ])

        let symbolConfig = UIImage.SymbolConfiguration(pointSize: 19, weight: .regular)
        for (index, destination) in destinations.enumerated() {
            let button = UIButton(type: .custom)
            button.tag = index
            button.accessibilityLabel = destination.title
            button.accessibilityIdentifier = "apollo.tab.\(destination.route)"
            button.addTarget(self, action: #selector(dockTapped(_:)), for: .touchUpInside)
            row.addArrangedSubview(button)

            let selection = UIView(frame: .zero)
            selection.backgroundColor = UIColor { traits in
                traits.userInterfaceStyle == .dark
                    ? UIColor.white.withAlphaComponent(0.12)
                    : UIColor.black.withAlphaComponent(0.075)
            }
            selection.layer.cornerRadius = 17
            selection.isUserInteractionEnabled = false
            selection.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(selection)

            let icon = UIImageView(image: UIImage(systemName: destination.symbol, withConfiguration: symbolConfig))
            icon.contentMode = .center
            icon.isUserInteractionEnabled = false
            icon.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(icon)

            let badge = UIView(frame: .zero)
            badge.backgroundColor = .systemBlue
            badge.layer.cornerRadius = 3
            badge.isHidden = true
            badge.isUserInteractionEnabled = false
            badge.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(badge)

            NSLayoutConstraint.activate([
                selection.centerXAnchor.constraint(equalTo: button.centerXAnchor),
                selection.centerYAnchor.constraint(equalTo: button.centerYAnchor),
                selection.widthAnchor.constraint(equalToConstant: 34),
                selection.heightAnchor.constraint(equalToConstant: 34),
                icon.centerXAnchor.constraint(equalTo: button.centerXAnchor),
                icon.centerYAnchor.constraint(equalTo: button.centerYAnchor),
                icon.widthAnchor.constraint(equalToConstant: 26),
                icon.heightAnchor.constraint(equalToConstant: 26),
                badge.leadingAnchor.constraint(equalTo: icon.trailingAnchor, constant: -2),
                badge.topAnchor.constraint(equalTo: icon.topAnchor, constant: 1),
                badge.widthAnchor.constraint(equalToConstant: 6),
                badge.heightAnchor.constraint(equalToConstant: 6)
            ])
            dockItems.append(DockItem(button: button, selection: selection, icon: icon, badge: badge))
        }

        view.addSubview(dock)
        let height = dock.heightAnchor.constraint(equalToConstant: 58 + view.safeAreaInsets.bottom)
        dockHeightConstraint = height
        NSLayoutConstraint.activate([
            dock.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            dock.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            dock.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            height
        ])

        selectRoute(currentRoute, animated: false)
        view.bringSubviewToFront(dock)
    }

    @objc private func dockTapped(_ button: UIButton) {
        guard destinations.indices.contains(button.tag) else { return }
        let destination = destinations[button.tag]
        let isReselection = destination.route == currentRoute
        selectRoute(destination.route, animated: true)

        UISelectionFeedbackGenerator().selectionChanged()

        guard bridgeIsReady else { return }
        evaluateJavaScript(
            "window.apolloNativeNavigate?.(\(Self.javaScriptLiteral(destination.route)), \(isReselection ? "true" : "false"))"
        )
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
            if let route = body["route"] as? String {
                selectRoute(route)
            }
        case "routeChanged":
            if let route = body["route"] as? String {
                selectRoute(route)
            }
        case "themeChanged":
            if let theme = body["theme"] as? String {
                applyTheme(theme, preference: body["preference"] as? String)
            }
        case "badgeChanged":
            setApolloBadge(body["visible"] as? Bool ?? false)
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

    private func selectRoute(_ route: String, animated: Bool = false) {
        guard destinations.contains(where: { $0.route == route }) else { return }
        currentRoute = route
        for (index, item) in dockItems.enumerated() {
            let selected = destinations[index].route == route
            item.button.accessibilityTraits = selected ? [.button, .selected] : .button
            item.icon.tintColor = selected ? .label : .secondaryLabel
            let changes = {
                item.selection.alpha = selected ? 1 : 0
                item.selection.transform = selected ? .identity : CGAffineTransform(scaleX: 0.86, y: 0.86)
            }
            if animated && !UIAccessibility.isReduceMotionEnabled {
                UIView.animate(withDuration: 0.18, delay: 0, options: [.beginFromCurrentState, .allowUserInteraction], animations: changes)
            } else {
                changes()
            }
        }
    }

    private func setApolloBadge(_ visible: Bool) {
        guard let index = destinations.firstIndex(where: { $0.route == "apollo" }) else { return }
        dockItems[index].badge.isHidden = !visible
        dockItems[index].button.accessibilityValue = visible ? "Response ready" : nil
    }

    private func applyTheme(_ theme: String, preference: String?) {
        if preference == "system" {
            overrideUserInterfaceStyle = .unspecified
            return
        }
        switch theme {
        case "light": overrideUserInterfaceStyle = .light
        case "dark": overrideUserInterfaceStyle = .dark
        default: overrideUserInterfaceStyle = .unspecified
        }
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

    private func observeKeyboard() {
        let center = NotificationCenter.default
        keyboardObservers.append(
            center.addObserver(forName: UIResponder.keyboardWillShowNotification, object: nil, queue: .main) { [weak self] notification in
                self?.setTabBarHiddenForKeyboard(true, notification: notification)
            }
        )
        keyboardObservers.append(
            center.addObserver(forName: UIResponder.keyboardWillHideNotification, object: nil, queue: .main) { [weak self] notification in
                self?.setTabBarHiddenForKeyboard(false, notification: notification)
            }
        )
    }

    private func setTabBarHiddenForKeyboard(_ hidden: Bool, notification: Notification) {
        let duration = notification.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double ?? 0.25
        let curveRaw = notification.userInfo?[UIResponder.keyboardAnimationCurveUserInfoKey] as? UInt ?? 7
        let options = UIView.AnimationOptions(rawValue: curveRaw << 16)
        let transform = hidden ? CGAffineTransform(translationX: 0, y: dock.bounds.height + 8) : .identity

        UIView.animate(
            withDuration: UIAccessibility.isReduceMotionEnabled ? 0 : duration,
            delay: 0,
            options: [options, .beginFromCurrentState, .allowUserInteraction]
        ) {
            self.dock.transform = transform
            self.dock.alpha = hidden ? 0 : 1
        }
    }
}
