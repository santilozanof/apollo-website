# Apollo on iPhone Shortcuts

Apollo's existing private Tailscale HTTPS origin is the base of these links. Open them with the Shortcuts **Open URLs** action while the iPhone is connected to the same tailnet and authenticated in Apollo's normal browser session. These links prepare an action in Apollo; the user taps **Add**, **Send**, or the water amount to save it. No bearer token or private API key belongs in the shortcut.

| Shortcut | URL path after the private Apollo origin | Result |
| --- | --- | --- |
| Quick-add task | `/?tab=tasks#title=Buy%20coffee` | Opens Tasks with the title filled in. Review and tap Add. |
| Ask Apollo | `/?tab=apollo#prompt=Plan%20my%20day` | Opens Chat with a draft prompt. Review and tap Send. |
| Log 710 mL Owala | `/?tab=routines&view=water&amount=710` | Opens Routines and focuses **+710 ml**. Tap once to log. |
| Daily Debrief | `/?tab=home&view=debrief` | Opens the briefing. |
| Music Insights | `/?tab=music&view=insights` | Opens listening insights. |
| Monthly Recap | `/?tab=music&view=recaps` | Opens the most recent completed month's recap. |

For a dynamic task or prompt, use Shortcuts' **URL Encode** action on the text and append its result after `#title=` or `#prompt=`. The fragment keeps that text out of the HTTP request; Apollo immediately removes it from the visible URL after reading it. The shortcut still contains the text in its own history and should be treated as personal data. The app never auto-submits a write from a link, so opening the shortcut twice does not create duplicate tasks or hydration entries.

Direct creation of a Studio note from Shortcuts is not supported: notes require a selected Studio project and an authenticated write flow. Use the Studio UI for that workflow. These are web deep links; no native Siri intent or direct FL Studio control is claimed.
