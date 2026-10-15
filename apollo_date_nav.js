/* One date-navigation layout for Calendar and Routines. Existing buttons keep
   their listeners; this module only moves them into the shared presentation. */
(() => {
    if (window.ApolloDateNav) return;

    function mount({ view, toolbar, context, add, today, previous, next }) {
        const page = document.querySelector(view);
        if (page?.querySelector(".apollo-date-nav")) return true;
        const controls = page?.querySelector(toolbar);
        if (!page || !controls) return false;
        const nodes = [context, add, today, previous, next]
            .map(selector => page.querySelector(selector));
        if (nodes.some(node => !node)) return false;
        const [dateLabel, addButton, todayButton, previousButton, nextButton] = nodes;
        controls.className = "apollo-date-nav";
        controls.setAttribute("aria-label", "Date navigation");
        const actions = document.createElement("div");
        actions.className = "apollo-date-nav-actions";
        dateLabel.className = "apollo-date-nav-context";
        addButton.className = "apollo-date-nav-button apollo-date-nav-add";
        addButton.setAttribute("aria-label", addButton.getAttribute("aria-label") || "New routine");
        addButton.textContent = "+";
        todayButton.className = "apollo-date-nav-button apollo-date-nav-today";
        previousButton.className = "apollo-date-nav-button apollo-date-nav-arrow";
        nextButton.className = "apollo-date-nav-button apollo-date-nav-arrow";
        actions.append(addButton, todayButton, previousButton, nextButton);
        controls.replaceChildren(dateLabel, actions);
        if (controls.parentElement?.tagName === "HEADER") {
            controls.parentElement.after(controls);
        }
        if (view === "#routinesView") {
            const syncToday = () => {
                const current = dateLabel.textContent.trim() === "Today";
                todayButton.hidden = false;
                todayButton.disabled = current;
                todayButton.setAttribute("aria-current", current ? "date" : "false");
            };
            new MutationObserver(syncToday).observe(dateLabel, { childList: true, characterData: true, subtree: true });
            new MutationObserver(() => { if (todayButton.hidden) syncToday(); })
                .observe(todayButton, { attributes: true, attributeFilter: ["hidden"] });
            syncToday();
        }
        return true;
    }

    window.ApolloDateNav = {
        mountCalendar: () => mount({
            view: "#calendarView", toolbar: ".apollo-week-controls",
            context: "#apolloWeekMonth", add: "#apolloWeekAdd",
            today: "#apolloWeekToday", previous: "#apolloWeekPrev", next: "#apolloWeekNext"
        }),
        mountRoutines: () => mount({
            view: "#routinesView", toolbar: ".routine-toolbar",
            context: "#routineDateLabel", add: "#routineCreate",
            today: "#routineToday", previous: '[data-date-move="-1"]', next: '[data-date-move="1"]'
        })
    };
})();
