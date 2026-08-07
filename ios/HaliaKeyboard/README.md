# Halia Templates keyboard (iOS)

A tiny iOS app plus a custom keyboard that puts your Halia outreach templates one tap away inside
WhatsApp, Messages, Mail, or any app with a text field. The host app signs in with your Halia
extension token and syncs your templates; the keyboard reads them from a shared App Group and
inserts the one you tap. The keyboard makes no network call, so it needs **no Full Access**.

This is templates only. There is no client lookup and no grade, by design.

## What is here

```
Shared/                (add to BOTH targets)
  AppGroup.swift        shared App Group id + keys       <-- set your group id here
  Template.swift        the template model
  TemplateStore.swift   read/write templates to the App Group
HostApp/               (add to the APP target only)
  HaliaTemplatesApp.swift   @main entry
  RootView.swift            connect, sync, set name, guide
  HaliaAPI.swift            GET /v1/extension/context
  TokenStore.swift          token in the Keychain
Keyboard/              (add to the KEYBOARD target only)
  KeyboardViewController.swift   the keyboard UI + insert
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

7. **Keep Full Access off.** Open the keyboard's `Info.plist`, `NSExtension`,
   `NSExtensionAttributes`, and confirm `RequestsOpenAccess` is `NO` (the default). The keyboard
   does not need it.

## Run it

1. Select the **HaliaTemplates** app scheme and run on your iPhone (or the simulator).
2. In the app: paste your token, leave the address as `https://haliascore.com`, tap **Connect and
   sync templates**. You should see the count of templates synced.
3. Enable the keyboard: **Settings, General, Keyboard, Keyboards, Add New Keyboard, Halia**. You do
   not need to allow Full Access.
4. Open WhatsApp (or Notes and Messages to test, since WhatsApp is not on the simulator), tap the
   🌐 globe until you are on the Halia keyboard, pick a category, and tap a template. It drops into
   the text field. Switch back to your normal keyboard with the globe to keep typing.

## The name slot

Templates use one placeholder, `{first_name}` (the server already fills `{sender}` and
`{catalog_link}`). The keyboard cannot read who you are messaging, so rather than guess a name and
risk inserting the wrong one, it drops in a neutral greeting: `{first_name}` becomes "there", for
example "Dear there,". It reads cleanly and is never tied to a specific client. If you want to
personalise, overtype "there" with a real name in the chat after inserting.

## Notes and gotchas

- **Simulator testing:** the keyboard works in the simulator's Notes and Messages. WhatsApp itself
  is only on a real device.
- **Local backend:** if you point the address at `http://localhost:8000`, iOS App Transport Security
  will block the plain-http call. Use the https production address, or add an ATS exception for local
  testing.
- **Memory:** keyboard extensions have a tight memory budget. Templates are small and read lazily,
  so this stays well within it.
- **Zero-retention:** the app stores only your token (Keychain) and your templates and optional name
  (App Group) on the device. No customer data is involved.

## Known v1 limits and easy next steps

- No free-text search (a keyboard cannot host a text field). Category chips cover filtering. A search
  row built from the keyboard's own key buttons is a later option.
- Insert only. Sending is left to the user in WhatsApp, which is the safe default.
