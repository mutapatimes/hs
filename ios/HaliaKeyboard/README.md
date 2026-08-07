# Halia composer keyboard (iOS)

A small iOS app plus a custom keyboard that helps an associate send a personal, on-voice message to
a VIP without leaving WhatsApp. There is no grade here by design: the point is the message.

It works in two layers:

1. **Templates and store info, offline.** The host app signs in with your Halia extension token and
   syncs your templates into a shared App Group; the keyboard inserts the one you tap. The house
   catalogue rides along via the `{catalog_link}` template. You can also fill in **store-info
   snippets** (hours, directions, returns, care, size guide, contact) in the app, and they appear in
   the keyboard under a "Store info" category. This layer needs no network and no Full Access.
2. **The composer, with Full Access.** Copy the client's name or number in the chat, tap "Use copied
   client", and the keyboard looks them up. Then:
   - templates fill with their real name;
   - the intent chips **draft** a personal message in your house voice, which you can **refine**
     (warmer / shorter / more formal) before it goes in;
   - **Reply** drafts a response to a message you copied from the client;
   - **Nudge basket** appears when the client left an open basket, and drafts a warm recovery note
     with the checkout link;
   - **Suggest pieces** recommends products from your catalogue, sent as a branded catalogue link;
   - **Mark contacted** logs the outreach to your shared team pipeline so nobody double-messages.

   This layer makes live calls, so it needs Full Access.

A **Client / Team** toggle sits at the top. Client mode (the above) writes a message *to* the client.
Team mode writes *about* the client, for a colleague: **Handoff** drafts a short internal note (who
they are, what they want, the next step) to paste into Slack, Teams, or a team chat. The internal note
never carries Halia's grade language: the phrase "hidden VIP" is both forbidden in the prompt and
scrubbed from the result, so it can never reach a teammate.

The keyboard never reads the WhatsApp screen. The client is identified only by what you copy.

## What is here

```
Shared/                (add to BOTH targets)
  AppGroup.swift        shared App Group id + keys       <-- set your group id here
  Credentials.swift     token + address in the App Group (so the keyboard can call live)
  ClientRef.swift       classify a copied string into email / phone / name
  Template.swift        the template model + name fill
  TemplateStore.swift   read/write templates to the App Group
  HaliaAPI.swift        /v1/extension: context (templates), lookup, draft, suggest, catalogue
HostApp/               (add to the APP target only)
  HaliaTemplatesApp.swift   @main entry
  RootView.swift            connect, sync, guide
Keyboard/              (add to the KEYBOARD target only)
  KeyboardViewController.swift   the composer UI (client bar, intents, templates, insert)
```

## Requirements

- Xcode 15 or newer, iOS 15+ deployment target.
- An Apple ID for signing. A free personal team is enough to run on your own iPhone; a paid Apple
  Developer account ($99/yr) is only needed to ship to TestFlight or the App Store.
- Your Halia extension token (Halia dashboard, Settings, generate extension token. Same token the
  Chrome extension uses).

## One-time Xcode setup (about 10 minutes)

1. **Create the app.** Xcode, File, New, Project, iOS, App. Name it `HaliaTemplates`, interface
   SwiftUI, language Swift. Set the deployment target to iOS 15. Pick a bundle id you own, for
   example `com.yourco.haliatemplates`.

2. **Add the source.** Delete the auto-generated `ContentView.swift` and the generated
   `…App.swift`. Drag the `Shared/` and `HostApp/` files into the project, ticking the
   **HaliaTemplates** app target when prompted.

3. **Add the keyboard.** File, New, Target, **Custom Keyboard Extension**. Name it `HaliaKeyboard`.
   Xcode generates a `KeyboardViewController.swift`; replace its contents with the one in
   `Keyboard/KeyboardViewController.swift` here (or delete the generated file and add ours to the
   **HaliaKeyboard** target).

4. **Set target membership.** Select each file in `Shared/` and, in the File Inspector, tick **both**
   `HaliaTemplates` and `HaliaKeyboard` under Target Membership. `HostApp/` files stay on the app
   target only; `Keyboard/` stays on the keyboard target only.

5. **Turn on App Groups on both targets.** Select the project, the `HaliaTemplates` target, Signing
   and Capabilities, `+ Capability`, **App Groups**, and add a group such as
   `group.com.yourco.haliatemplates`. Do the same on the `HaliaKeyboard` target with the **same**
   group. Then put that exact id in `Shared/AppGroup.swift` (`AppGroup.identifier`).

6. **Signing.** On both targets, pick your team. If you use a free personal team, choose your own
   device as the run destination.

7. **Turn Full Access ON in the manifest.** Open the keyboard's `Info.plist`, `NSExtension`,
   `NSExtensionAttributes`, and set `RequestsOpenAccess` to `YES`. The composer needs it to read the
   copied client and reach your Halia account. (Templates still work if a user leaves Full Access
   off in Settings; only the lookup and draft features go quiet.)

## Run it

1. Select the **HaliaTemplates** app scheme and run on your iPhone (or the simulator).
2. In the app: paste your token, leave the address as `https://haliascore.com`, tap **Connect and
   sync templates**. You should see the count of templates synced.
3. Enable the keyboard: **Settings, General, Keyboard, Keyboards, Add New Keyboard, Halia**, then
   open Halia in that list and turn on **Allow Full Access** (needed for the composer).
4. Open WhatsApp (or Notes and Messages to test, since WhatsApp is not on the simulator) and tap the
   🌐 globe until you are on the Halia keyboard.
   - **Templates:** pick a category and tap a template. It drops into the text field.
   - **Personalise:** copy the client's name or number in the chat, tap **Use copied client**. Now
     templates fill with their real name, and the **Draft** chips write a personal message you can
     insert and edit.
   - **Suggest pieces:** tap it to recommend products for this client, tick the ones you like, then
     **Send catalogue** to drop a branded catalogue link (on your own domain) into the chat.
   - **Reply:** copy the client's last message, tap **Reply**, and it drafts a response to it.
   - **Refine:** a drafted message shows in the keyboard first. Tap **Warmer**, **Shorter**, or
     **More formal** to adjust it, then **Insert** to place it in the chat.
   - **Nudge basket:** if the client has an open basket, a 🧺 chip appears. Tap it to draft a warm
     recovery message; **Insert** places it with the checkout link appended.
   - **Mark contacted:** logs this outreach to your shared pipeline (Shopify), so the team sees it.

## The name slot

Templates use one placeholder, `{first_name}` (the server already fills `{sender}` and
`{catalog_link}`). When a client is looked up, it fills with their real first name. When no client
is set, the placeholder is removed and the small gap tidied, so "Dear {first_name}," reads as "Dear,"
and "{first_name}, we are open" reads as "We are open". A template that opens with `{catalog_link}`
is left exactly as-is, so the URL is never mangled.

## Privacy and Full Access

Full Access is what lets the keyboard read the client you copied and reach your Halia account, and it
is the permission iOS frames as "this keyboard can transmit what you type". Halia acts only on what
you copy and on the chips you tap. It does not read or send what you type in other fields. The device
stores only your token and address and your synced templates (in the App Group). Customer records
stay in your Halia account; the lookup and draft are used in-flight and not stored. For stronger
secrecy of the token, a shared Keychain access group is the hardening step over the App Group.

## Notes and gotchas

- **Simulator testing:** templates work in the simulator's Notes and Messages. WhatsApp is only on a
  real device, and copy-to-lookup is easiest to feel there.
- **Local backend:** if you point the address at `http://localhost:8000`, iOS App Transport Security
  will block the plain-http call. Use the https production address, or add an ATS exception for local
  testing.
- **Memory:** keyboard extensions have a tight memory budget. Templates are small and read lazily.
- **Reading the clipboard** shows the iOS paste banner. That is expected: it only happens when you
  tap "Use copied client", never silently.

## Known limits and next steps

- The keyboard cannot read the incoming thread, so a draft is built from the client plus the intent
  you tap, not from replying to their last message. You review and edit before sending.
- Copy-to-lookup is one gesture. It is the price of not being able to read the WhatsApp screen.
- No free-text search (a keyboard cannot host a text field). Category chips cover filtering.
- Suggestions and drafts need an AI key configured on the Halia backend. Without one, drafts fall
  back to your templates and Suggest returns nothing rather than a guess, so the keyboard is never a
  dead button.
- Send catalogue inserts the branded link on its own. Pair it with a drafted message first for a
  complete note.
