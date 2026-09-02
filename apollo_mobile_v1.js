/* =========================================================
   APOLLO MOBILE V1
   Mobile behavior only.
   ========================================================= */

(() => {

    const mobileQuery =
        window.matchMedia(
            "(max-width: 760px)"
        );


    function applyMode() {

        document.documentElement
            .classList.toggle(
                "apollo-mobile-v1",
                mobileQuery.matches
            );

    }


    applyMode();


    mobileQuery.addEventListener?.(
        "change",
        applyMode
    );


    /* -----------------------------------------------------
       Give every bottom-nav item a useful accessibility name.
       Existing navigation click behavior remains untouched.
       ----------------------------------------------------- */

    document
        .querySelectorAll(
            ".sidebar .nav-button"
        )
        .forEach(
            button => {

                const label =
                    button.querySelector(
                        ".nav-label"
                    );


                if (
                    label
                    && !button.getAttribute(
                        "aria-label"
                    )
                ) {

                    const name =
                        label.textContent
                            .trim();


                    if (name) {

                        button.setAttribute(
                            "aria-label",
                            name
                        );

                    }

                }

            }
        );


    /* -----------------------------------------------------
       iPhone keyboard:
       hide bottom navigation while typing so it does not
       compete with the composer or modal fields.
       ----------------------------------------------------- */

    function updateKeyboardState() {

        if (!mobileQuery.matches) {

            document.body.classList.remove(
                "apollo-mobile-keyboard-open"
            );

            return;

        }


        const viewport =
            window.visualViewport;


        if (!viewport) {
            return;
        }


        const layoutHeight =
            Math.max(
                window.innerHeight,
                document.documentElement
                    .clientHeight
            );


        const obscured =
            Math.max(
                0,
                layoutHeight
                - viewport.height
                - viewport.offsetTop
            );


        document.body.classList.toggle(
            "apollo-mobile-keyboard-open",
            obscured > 110
        );

    }


    window.visualViewport
        ?.addEventListener(
            "resize",
            updateKeyboardState
        );


    window.visualViewport
        ?.addEventListener(
            "scroll",
            updateKeyboardState
        );


    window.addEventListener(
        "orientationchange",
        () => {

            setTimeout(
                updateKeyboardState,
                180
            );

        }
    );


    /* -----------------------------------------------------
       On touch navigation, remove any lingering hover state.
       ----------------------------------------------------- */

    document.addEventListener(
        "touchstart",
        event => {

            if (
                !mobileQuery.matches
            ) {
                return;
            }


            const button =
                event.target.closest?.(
                    ".nav-button"
                );


            if (!button) {
                return;
            }


            button.classList.add(
                "apollo-mobile-touching"
            );


            setTimeout(
                () =>
                    button.classList.remove(
                        "apollo-mobile-touching"
                    ),
                150
            );

        },
        {
            passive: true
        }
    );


    updateKeyboardState();

})();

/* =========================================================
   APOLLO MOBILE V1.2
   HISTORY PORTAL
   ========================================================= */

(() => {

    const mobile =
        window.matchMedia(
            "(max-width: 760px)"
        );


    const panel =
        document.getElementById(
            "apolloHistoryStrip"
        );


    if (!panel) {
        return;
    }


    const originalParent =
        panel.parentNode;


    const originalNextSibling =
        panel.nextSibling;


    function mountHistory() {

        if (mobile.matches) {

            /*
             * The old DOM puts History inside the composer.
             * On iPhone that traps it inside the composer's
             * stacking context.
             *
             * Portal it directly to BODY instead.
             */

            if (
                panel.parentNode
                !== document.body
            ) {

                document.body.appendChild(
                    panel
                );

            }

        }
        else {

            if (
                panel.parentNode
                === document.body
                && originalParent
            ) {

                if (
                    originalNextSibling
                    && originalNextSibling.parentNode
                    === originalParent
                ) {

                    originalParent.insertBefore(
                        panel,
                        originalNextSibling
                    );

                }
                else {

                    originalParent.appendChild(
                        panel
                    );

                }

            }

        }

    }


    function syncHistoryState() {

        const open =
            panel.classList.contains(
                "open"
            );


        document.body.classList.toggle(
            "apollo-mobile-history-open",
            mobile.matches
            && open
        );


        if (
            mobile.matches
            && open
        ) {

            /*
             * Existing desktop code autofocuses Search.
             * Don't summon the iPhone keyboard every time
             * History opens.
             */

            setTimeout(
                () => {

                    const search =
                        document.getElementById(
                            "apolloHistorySearch"
                        );


                    if (
                        search
                        && document.activeElement
                        === search
                    ) {

                        search.blur();

                    }

                },
                230
            );

        }

    }


    const observer =
        new MutationObserver(
            syncHistoryState
        );


    observer.observe(
        panel,
        {
            attributes: true,

            attributeFilter: [
                "class"
            ]
        }
    );


    mobile.addEventListener?.(
        "change",
        () => {

            mountHistory();

            syncHistoryState();

        }
    );


    mountHistory();

    syncHistoryState();

})();

/* =========================================================
   APOLLO MOBILE V1.4
   STABLE STATIC CHAT HEADER
   ========================================================= */

(() => {

    const mobile =
        window.matchMedia(
            "(max-width: 760px)"
        );

    const view =
        document.getElementById(
            "apolloView"
        );

    const header =
        document.getElementById(
            "apolloMobileChatHeader"
        );

    if (
        !view
        || !header
    ) {
        return;
    }


    const newChat =
        document.getElementById(
            "apolloMobileNewChat"
        );

    const history =
        document.getElementById(
            "apolloMobileHistory"
        );


    /*
     * One handler only.
     * No duplicate mobile-header listeners.
     */

    if (newChat) {

        newChat.onclick =
            event => {

                event.preventDefault();
                event.stopPropagation();


                if (
                    typeof window.apolloHistoryNewChat
                    === "function"
                ) {

                    window.apolloHistoryNewChat();

                    return;
                }


                document
                    .getElementById(
                        "apolloHeaderNewChat"
                    )
                    ?.click();

            };

    }


    if (history) {

        history.onclick =
            event => {

                event.preventDefault();
                event.stopPropagation();


                if (
                    typeof window.apolloOpenHistory
                    === "function"
                ) {

                    window.apolloOpenHistory();

                    return;
                }


                document
                    .getElementById(
                        "apolloHeaderHistory"
                    )
                    ?.click();

            };

    }


    function sync() {

        const visible =
            mobile.matches
            && view.classList.contains(
                "active"
            );


        header.classList.toggle(
            "is-visible",
            visible
        );


        if (visible) {

            header.removeAttribute(
                "hidden"
            );

        }
        else {

            header.setAttribute(
                "hidden",
                ""
            );

        }

    }


    const observer =
        new MutationObserver(
            sync
        );


    observer.observe(
        view,
        {
            attributes: true,

            attributeFilter: [
                "class"
            ]
        }
    );


    mobile.addEventListener?.(
        "change",
        sync
    );


    /*
     * iOS PWAs can restore a page from memory instead
     * of performing a fresh load. Re-sync on restoration.
     */

    window.addEventListener(
        "pageshow",
        sync
    );


    document.addEventListener(
        "visibilitychange",
        () => {

            if (
                document.visibilityState
                === "visible"
            ) {
                sync();
            }

        }
    );


    sync();

    setTimeout(
        sync,
        100
    );

    setTimeout(
        sync,
        500
    );

})();

/* =========================================================
   APOLLO MOBILE V1.6
   iOS KEYBOARD + SAFE AREA STATE
   ========================================================= */

(() => {

    const mobile =
        window.matchMedia(
            "(max-width: 760px)"
        );


    const view =
        document.getElementById(
            "apolloView"
        );


    const header =
        document.getElementById(
            "apolloMobileChatHeader"
        );


    if (!view) {
        return;
    }


    function apolloIsFocused() {

        const active =
            document.activeElement;


        if (!active) {
            return false;
        }


        return Boolean(
            active.closest?.(
                "#apolloView"
            )
            && (
                active.matches(
                    "textarea"
                )
                || active.matches(
                    "input"
                )
                || active.matches(
                    "[contenteditable='true']"
                )
            )
        );

    }


    function syncKeyboardFromFocus() {

        if (!mobile.matches) {

            document.body
                .classList.remove(
                    "apollo-mobile-keyboard-open"
                );

            return;
        }


        document.body
            .classList.toggle(
                "apollo-mobile-keyboard-open",
                apolloIsFocused()
            );

    }


    /*
     * iOS standalone mode is inconsistent with visualViewport.
     * Focus state is much more reliable.
     */

    document.addEventListener(
        "focusin",
        event => {

            if (
                !mobile.matches
            ) {
                return;
            }


            if (
                event.target.closest?.(
                    "#apolloView"
                )
            ) {

                document.body
                    .classList.add(
                        "apollo-mobile-keyboard-open"
                    );

            }

        }
    );


    document.addEventListener(
        "focusout",
        () => {

            setTimeout(
                syncKeyboardFromFocus,
                120
            );

        }
    );


    /* -----------------------------------------------------
       Header state
       ----------------------------------------------------- */

    function syncHeader() {

        if (!header) {
            return;
        }


        const visible =
            mobile.matches
            && view.classList.contains(
                "active"
            );


        if (visible) {

            header.removeAttribute(
                "hidden"
            );

            header.classList.add(
                "is-visible"
            );

        }
        else {

            header.classList.remove(
                "is-visible"
            );

            header.setAttribute(
                "hidden",
                ""
            );

        }

    }


    const viewObserver =
        new MutationObserver(
            syncHeader
        );


    viewObserver.observe(
        view,
        {
            attributes: true,
            attributeFilter: [
                "class"
            ]
        }
    );


    /* -----------------------------------------------------
       Sync iOS status-area color to actual Apollo background
       ----------------------------------------------------- */

    let themeMeta =
        document.querySelector(
            'meta[name="theme-color"]'
        );


    if (!themeMeta) {

        themeMeta =
            document.createElement(
                "meta"
            );


        themeMeta.name =
            "theme-color";


        document.head.appendChild(
            themeMeta
        );

    }


    function syncThemeColor() {

        const target =
            view.classList.contains(
                "active"
            )
                ? view
                : document.body;


        const background =
            getComputedStyle(
                target
            ).backgroundColor;


        if (background) {

            themeMeta.setAttribute(
                "content",
                background
            );

        }

    }


    const htmlObserver =
        new MutationObserver(
            () => {

                syncThemeColor();
                syncHeader();

            }
        );


    htmlObserver.observe(
        document.documentElement,
        {
            attributes: true,

            attributeFilter: [
                "data-theme",
                "class"
            ]
        }
    );


    window.addEventListener(
        "pageshow",
        () => {

            syncHeader();
            syncThemeColor();
            syncKeyboardFromFocus();

        }
    );


    document.addEventListener(
        "visibilitychange",
        () => {

            if (
                document.visibilityState
                === "visible"
            ) {

                syncHeader();
                syncThemeColor();
                syncKeyboardFromFocus();

            }

        }
    );


    mobile.addEventListener?.(
        "change",
        () => {

            syncHeader();
            syncThemeColor();
            syncKeyboardFromFocus();

        }
    );


    syncHeader();
    syncThemeColor();
    syncKeyboardFromFocus();

})();

/* =========================================================
   APOLLO MOBILE V1.7
   REAL TYPING STATE
   ========================================================= */

(() => {

    const mobile =
        window.matchMedia(
            "(max-width: 760px)"
        );


    function isTypingElement(
        element
    ) {

        if (!element) {
            return false;
        }


        if (
            element.matches?.(
                "textarea"
            )
        ) {
            return true;
        }


        if (
            element.matches?.(
                "input"
            )
        ) {

            const type =
                (
                    element.type
                    || "text"
                ).toLowerCase();


            return ![
                "button",
                "submit",
                "reset",
                "checkbox",
                "radio",
                "range",
                "color",
                "file"
            ].includes(
                type
            );

        }


        return (
            element.isContentEditable
            === true
        );

    }


    function sync() {

        const typing =
            mobile.matches
            && isTypingElement(
                document.activeElement
            );


        document.body
            .classList.toggle(
                "apollo-mobile-typing",
                typing
            );

    }


    document.addEventListener(
        "focusin",
        () => {

            requestAnimationFrame(
                sync
            );

        }
    );


    document.addEventListener(
        "focusout",
        () => {

            setTimeout(
                sync,
                120
            );

        }
    );


    window.addEventListener(
        "pageshow",
        sync
    );


    document.addEventListener(
        "visibilitychange",
        () => {

            if (
                document.visibilityState
                === "visible"
            ) {
                sync();
            }

        }
    );


    mobile.addEventListener?.(
        "change",
        sync
    );


    sync();

})();

/* =========================================================
   APOLLO MOBILE — ACTUAL KEYBOARD DETECTION
   Focus alone does NOT count.
   ========================================================= */

(() => {

    const mobile =
        window.matchMedia(
            "(max-width: 760px)"
        );

    const viewport =
        window.visualViewport;

    let fullHeight =
        viewport?.height
        || window.innerHeight;


    function editable(element) {

        if (!element) {
            return false;
        }

        if (
            element.matches?.(
                "textarea, input:not([type='button']):not([type='submit']):not([type='file'])"
            )
        ) {
            return true;
        }

        return element.isContentEditable;
    }


    function sync() {

        if (!mobile.matches) {

            document.body.classList.remove(
                "apollo-mobile-keyboard-visible"
            );

            return;
        }


        const height =
            viewport?.height
            || window.innerHeight;


        const focused =
            editable(
                document.activeElement
            );


        if (!focused) {

            fullHeight =
                Math.max(
                    fullHeight,
                    height
                );

        }


        const keyboardVisible =
            focused
            && (
                fullHeight
                - height
            ) > 120;


        document.body.classList.toggle(
            "apollo-mobile-keyboard-visible",
            keyboardVisible
        );

    }


    viewport?.addEventListener(
        "resize",
        sync
    );

    viewport?.addEventListener(
        "scroll",
        sync
    );

    window.addEventListener(
        "resize",
        sync
    );

    document.addEventListener(
        "focusin",
        () => setTimeout(sync, 100)
    );

    document.addEventListener(
        "focusout",
        () => setTimeout(sync, 120)
    );

    window.addEventListener(
        "pageshow",
        sync
    );

    sync();

})();
