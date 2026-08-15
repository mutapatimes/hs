# Adding the Widget, Share, and CallKit targets in Xcode

The Swift for three more app extensions is already written and sitting in the project, but the
Xcode **targets** don't exist yet, so nothing builds or installs them:

| Folder (on disk)     | What it is                        | Entry point                    |
|----------------------|-----------------------------------|--------------------------------|
| `HaliaWidget/`       | Home/Lock-Screen "Reach today" widget | `HaliaWidgetBundle.swift` (`@main`) |
| `HaliaShare/`        | Share-sheet extension (save a product/link into Halia) | `ShareViewController.swift` |
| `HaliaCallDirectory/`| CallKit VIP caller-ID             | `CallDirectoryHandler.swift`   |

This guide creates each one. Do them one at a time and build after each — it's much easier to find a
mistake against one new target than three.

---

## Facts you'll reuse for every target

- **App Group** (all targets share it): `group.com.haliascore.haliatemplates`
- **Bundle ID pattern**: the container app is `com.haliascore.HaliaTemplates`, so each extension must be
  **prefixed by it**: `com.haliascore.HaliaTemplates.HaliaWidget`, `….HaliaShare`, `….HaliaCallDirectory`.
- **Deployment target**: iOS **18.5** (match the app; set it if the wizard defaults higher/lower).
- **Signing Team**: set the same Team on each new target (Signing & Capabilities → Team).
- **The shared code**: the extensions use helper types in `HaliaTemplates/HaliaKeyboard/Shared/`
  (`AppGroup`, `Credentials`, `HaliaAPI`, `Template`, `TemplateStore`, `DirectoryStore`, `ClientRef`,
  `StoreInfo`). Because each extension is its own binary, **it must compile its own copy of the Shared
  files it needs.** The simple, safe rule below: tick *all* of `Shared/` into the new target. Extra
  files are harmless (unused code is stripped).

### The one Xcode habit that makes this painless

This project uses **synchronized folder groups** (the blue-ish folders in the navigator). You do **not**
add files with "Add Files…". Instead you select a file and toggle its **Target Membership** in the File
Inspector, and Xcode edits the project for you:

1. Select the file(s) in the Project Navigator (left).
2. Open the File Inspector: **View → Inspectors → File**, or **⌥⌘1**.
3. Under **Target Membership**, tick the box for the target that should compile the file.

That's the move you'll repeat for the Shared files in every target below.

---

## A. Widget — "Reach today" (Home / Lock Screen)

1. **File → New → Target…** → iOS → **Widget Extension** → Next.
2. Product Name: **`HaliaWidget`**.
   - **Uncheck "Include Live Activity."**
   - **Uncheck "Include Configuration App Intent"** — this widget is a `StaticConfiguration`
     (`TodayWidget` uses a plain `TimelineProvider`), so the configuration intent would just add a
     second, conflicting `@main`.
   - "Embed in Application" / project: **HaliaTemplates**. Finish. If asked to activate the new scheme,
     **Activate**.
3. **Remove the wizard's placeholder.** The template drops a generated `HaliaWidget.swift` (with its own
   `@main`) into the folder. You already have `HaliaWidgetBundle.swift` as the `@main` entry, so **delete
   the generated placeholder** (Move to Trash) to avoid *"'main' attribute can only apply to one type"*.
   Keep your `HaliaWidgetBundle.swift` and `TodayWidget.swift`.
4. Confirm `HaliaWidgetBundle.swift` and `TodayWidget.swift` show **HaliaWidget** ticked in Target
   Membership (they should, since they're in the widget's folder).
5. **Add the shared code:** select every file in `HaliaTemplates/HaliaKeyboard/Shared/` and tick
   **HaliaWidget** in Target Membership. (Minimum the widget actually needs: `AppGroup`, `Credentials`,
   `HaliaAPI`, `Template` — but ticking all of `Shared/` is the safe rule.)
6. **App Group:** select the **HaliaWidget** target → **Signing & Capabilities** → **+ Capability** →
   **App Groups** → tick `group.com.haliascore.haliatemplates`. (Without this the widget can't read the
   token the app saved, so it only ever shows the sample data.)
7. Set **Bundle Identifier** = `com.haliascore.HaliaTemplates.HaliaWidget` and the **Team**; set
   **Deployment Target** 18.5 if needed.
8. Build the **HaliaTemplates** scheme (⌘B). Then run the app, long-press the Home Screen → **+** → search
   "Halia" → add the **Reach today** widget.

---

## B. Share extension — save into Halia from the share sheet

1. **File → New → Target…** → iOS → **Share Extension** → Next.
2. Product Name: **`HaliaShare`**. Embed in **HaliaTemplates**. Finish → Activate.
3. **Remove the wizard's placeholders.** The Share template generates a `ShareViewController.swift` and
   usually a `MainInterface.storyboard`. You already have `ShareViewController.swift` **and** a SwiftUI
   `ShareRootView.swift`, and you're not using a storyboard. So:
   - **Delete the generated `ShareViewController.swift`** (Move to Trash) — then confirm *your*
     `HaliaShare/ShareViewController.swift` is present and has **HaliaShare** ticked.
   - **Delete `MainInterface.storyboard`** (Move to Trash).
   - In the **HaliaShare Info.plist**, under `NSExtension`, **remove the `NSExtensionMainStoryboard`
     key** and replace it with **`NSExtensionPrincipalClass`** = `$(PRODUCT_MODULE_NAME).ShareViewController`.
     (This is what tells iOS to launch your view controller directly instead of a storyboard.)
4. Confirm `ShareViewController.swift` and `ShareRootView.swift` show **HaliaShare** in Target Membership.
5. **Add the shared code:** tick all of `Shared/` into **HaliaShare** (it uses `AppGroup`, `Credentials`,
   `HaliaAPI`, `ClientRef`).
6. **App Group:** HaliaShare target → Signing & Capabilities → + Capability → **App Groups** → tick
   `group.com.haliascore.haliatemplates`.
7. Bundle ID `com.haliascore.HaliaTemplates.HaliaShare`, Team, Deployment Target 18.5.
8. *(Optional, controls what shows up in the share sheet.)* The `NSExtensionActivationRule` in the Info.plist
   decides which shared content Halia offers to accept (e.g. one web URL / one image). Leave the default to
   start; tighten later.
9. Build. Test by sharing a link/photo from Safari or Photos → **Halia** should appear in the sheet.

---

## C. CallKit Call Directory — VIP caller ID

1. **File → New → Target…** → iOS → **Call Directory Extension** → Next.
2. Product Name: **`HaliaCallDirectory`**. Embed in **HaliaTemplates**. Finish → Activate.
3. **Remove the wizard's placeholder** `CallDirectoryHandler.swift`, then confirm *your*
   `HaliaCallDirectory/CallDirectoryHandler.swift` is present with **HaliaCallDirectory** ticked. (Only one
   `CallDirectoryHandler` class may exist in the target.)
4. **Add the shared code:** tick all of `Shared/` into **HaliaCallDirectory** (it uses `AppGroup` and
   `DirectoryStore`).
5. **App Group:** HaliaCallDirectory target → Signing & Capabilities → + Capability → **App Groups** → tick
   `group.com.haliascore.haliatemplates`. This is essential — the extension reads the VIP list the app
   wrote into the shared App Group.
6. Bundle ID `com.haliascore.HaliaTemplates.HaliaCallDirectory`, Team, Deployment Target 18.5.
7. Build. To see it: run the app (it writes the directory + calls `CallDirectory.refresh()`), then Settings
   → Phone → Call Blocking & Identification → enable **Halia**. Incoming calls from saved VIP numbers then
   show the label.

---

## Common pitfalls (all three)

- **"'main' attribute can only apply to one type" / duplicate symbols** → you left the wizard's generated
  Swift file in alongside your real one. Delete the generated placeholder.
- **Extension builds but shows only sample/empty data on device** → missing **App Group** capability on
  that target, or the group id is mistyped. It must be exactly `group.com.haliascore.haliatemplates` on the
  app *and* the extension.
- **"cannot find type 'HaliaAPI' / 'AppGroup' in scope"** → you didn't tick the `Shared/` files into that
  target. Extensions don't inherit the app's code.
- **"embedded binary's bundle identifier is not prefixed with the parent app's"** → fix the extension's
  Bundle ID to start with `com.haliascore.HaliaTemplates.`.
- **Provisioning/"failed to register bundle identifier"** → each extension needs its own App ID with the
  App Groups capability. With automatic signing, selecting your Team on the target usually registers it; if
  not, add the App ID + App Group in the Apple Developer portal and let Xcode retry.

## Verify from the command line

After creating the targets, the schemes list should show the new targets, and this should still pass:

```
cd ios/HaliaTemplates
xcodebuild -list -project HaliaTemplates.xcodeproj          # HaliaWidget / HaliaShare / HaliaCallDirectory now appear
xcodebuild build -project HaliaTemplates.xcodeproj \
  -scheme HaliaTemplates \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO
```

> Note: a **Call Directory** extension only actually runs on a real device (CallKit identification isn't
> exercised in the simulator), but it will still *build* in the simulator, which is what we're verifying.
