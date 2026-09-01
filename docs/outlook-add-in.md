# Halia in Outlook

A task pane beside the message an associate is writing or reading: who it is with, their standing,
the house templates, a selection or a basket to send, and a visit to book. Same endpoints as the
Chrome toolbar and the iPhone app, so nothing new has to be learned or maintained.

The gain over the toolbar is reach. `extension/content/gmail.js` covers Gmail in Chrome on a
desktop and nothing else; Outlook was not covered at all.

## Reading and writing are both first-class

**Reading a client's email**, every action opens a reply already written, through Outlook's own
reply form: pick a template, send a selection, book a visit, and the words arrive in a reply
window ready to send. "Read this for me" reads what the client wrote and comes back with where
the relationship stands, the moves worth making, and a ready reply, one tap from being open.
"Remember this" puts what they said (sizes, occasions) on their record. An unknown sender is one
tap from the book, through the same capture path as the shop floor.

The pane can be **pinned** (the pin icon in its corner, on the web and on Windows; Mac keeps
panes open by itself). Pinned, it stays up while the associate walks the inbox and re-identifies
each message: every sender's standing appears as they arrive on it.

**Writing**, the recipient is identified live as the To field is filled, templates land at the
cursor and fill an empty subject line, and "Polish my writing" rewrites the selected sentences in
the house voice, leaving the quoted thread and the signature alone.

## Sending logs itself

Sending a message to someone in the book puts a contact line on their record with no tap, at most
once per client per day, so a back-and-forth thread logs one line rather than five. The manual
"Log that I contacted them" button remains for everything else.

This runs on Outlook's on-send event with the `PromptUser` mode, which carries a guarantee worth
stating plainly: **if Halia is slow, broken or unreachable, Outlook sends the mail anyway.**
Nothing Halia does can hold up anyone's email. The handler reads the sign-in from the mailbox's
roaming settings (written when the associate signs in on the pane); on classic Outlook for
Windows the event runs in a JavaScript-only runtime, which is why roaming settings carry it
rather than the browser's own storage. Verify on a real classic client before promising it there.

## Where it runs

| Client | Compose pane | Reading pane |
|---|---|---|
| Outlook on the web | yes | yes |
| new Outlook on Windows | yes | yes |
| Outlook on Windows (classic) | yes | yes |
| Outlook on Mac | yes | yes |
| **Outlook on iOS / Android** | **no** | **no** |

Outlook on mobile runs read-mode add-ins only, and even that has to be declared and defended
separately, so the manifest deliberately declares no mobile form factor. Do not promise a phone
experience here: the iPhone app and the keyboard are Halia's phone surfaces.

This is also why the manifest is the **XML add-in-only** format rather than the newer unified JSON
manifest. The JSON manifest does not support Outlook on Mac, and boutiques run Macs.

## Getting it into a mailbox

No review by Microsoft is needed for either of these.

**One associate, to try it.** Go to <https://aka.ms/olksideload>, then My add-ins → Custom Addins →
Add a custom add-in → **Add from file**. Download the manifest first, from
`https://haliascore.com/addons/outlook/manifest.xml`; the "add from URL" option no longer exists.
In classic Outlook on Windows the add-in can take up to 24 hours to appear because of caching; on
the web it is immediate.

**The whole boutique.** Their IT administrator uploads the same manifest in the Microsoft 365 admin
centre under Settings → Integrated apps → Upload custom apps, and assigns it to people or groups.
Nothing to configure on each machine.

A Microsoft Marketplace listing is only needed for public discovery, and takes days of validation
plus up to about four weeks end to end. It is not needed to serve a named customer.

## Signing in

Outlook no longer issues the identity token that used to let an add-in recognise the signed-in
person silently, so the associate signs in by hand once per machine, with their work email and the
sign-in they were given. Seats are minted in the dashboard under Settings → Team, exactly as for
the Chrome extension and the iPhone app, and revoking one there stops the add-in too.

The token is kept in the browser profile's own storage on `haliascore.com`. On a shared machine
each profile pairs once, and the token should be treated like a password.

## How it is served

`halia/api/outlook_addon.py`. Two things about it are load-bearing:

* **The pane is hosted on our own origin.** Its calls to `/v1/extension/*` are therefore
  same-origin, and the CORS allow-list in `halia/api/app.py` stays as it is. Moving the pane to any
  other host would break every POST it makes.
* **The pane sets its own `Content-Security-Policy`.** `_security_headers_mw` puts
  `frame-ancestors 'none'` and `X-Frame-Options: DENY` on anything that does not, and Outlook
  loads task panes in an iframe. Without the exemption the pane is blank, with nothing in any log
  to say why. `tests/test_outlook_addon.py` pins this down.

The add-in id in `halia/config.py` (`OUTLOOK_ADDIN_ID`) must never change once a mailbox holds it:
Outlook keys the installed add-in on that GUID, so a new one installs a second copy alongside.

## Template shaping

The pane fills `{first_name}` and honours the greeting and sign-off toggles through
`window.HaliaShape` (`web/site/static/halia-shape.js`), the single copy of those rules. The Chrome
extension gets a byte-identical copy on disk because Manifest V3 forbids remote code;
`scripts/sync_shape.py` writes it and `tests/test_shape_sync.py` fails if the two drift.

The iOS keyboard still has its own implementation in `Shared/Template.swift` with a different
algorithm, so it can produce different output from the same template. That is a known divergence,
not something this add-in introduced.
