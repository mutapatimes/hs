# Halia iOS extensions — setup

Three places Halia shows up outside its own app, all reusing the keyboard's `Shared/` layer
(`HaliaAPI`, `Credentials`, `AppGroup`) and the App Group `group.com.haliascore.haliatemplates`.

Backend (already shipped, zero-retention, RAM cache only):
- `GET /v1/extension/today` — the "reach today" queue (new orders + gone-quiet). Powers the widget + App Intents.
- `GET /v1/extension/directory` — graded clients as E.164 `phone → "Name · grade"`, for CallKit.

Each extension calls these with the `X-Halia-Ext-Token` the host app already stores in the App Group,
so there is no separate sign-in.

---

## 1. Widget + App Intents  ← written, ready to wire

**Files**
- `HaliaWidget/TodayWidget.swift`, `HaliaWidget/HaliaWidgetBundle.swift` → the widget target
- `…/HostApp/HaliaAppIntents.swift` → the **host app** target (Siri / Shortcuts / Spotlight)
- `Shared/HaliaAPI.swift` already has `today()` + `HaliaAPI.TodayItem`

**Xcode steps**
1. File ▸ New ▸ Target ▸ **Widget Extension**. Name it `HaliaWidget`. Uncheck "Include Live Activity";
   uncheck "Include Configuration App Intent" (this widget is `StaticConfiguration`).
2. Delete the stub `HaliaWidget.swift`/bundle Xcode generates; add the two files above instead.
3. Select the `HaliaWidget` target ▸ **Signing & Capabilities** ▸ **+ App Groups** ▸ tick
   `group.com.haliascore.haliatemplates` (same id as the app + keyboard).
4. Add the shared files to the widget target: select `HaliaAPI.swift`, `Credentials.swift`,
   `AppGroup.swift` in the navigator ▸ File inspector ▸ **Target Membership** ▸ tick `HaliaWidget`.
5. `HaliaAppIntents.swift` needs **only** the host-app target ticked (App Shortcuts register from the app).
6. Build & run the app once, then long-press the Home Screen ▸ add the **Reach today** widget. Ask Siri
   "who should I reach today in Halia".

**Deep link:** the widget opens `halia://today`. Handle it in the host app's `.onOpenURL` (next to the
existing `halia://connect`) to route to the clients view.

---

## 2. Share Extension — "Send with Halia"  ← written, ready to wire

Share a client's name / email / phone from Contacts, Messages, Safari or the Shopify app and Halia
looks them up (grade, why, open basket) and drafts a message you can copy back into the chat.

**Files**
- `HaliaShare/ShareViewController.swift` (principal class), `HaliaShare/ShareRootView.swift` → the share target

**Xcode steps**
1. File ▸ New ▸ Target ▸ **Share Extension**. Name it `HaliaShare`.
2. Delete Xcode's stub `ShareViewController.swift`/`MainInterface.storyboard`; add the two files above.
3. **Signing & Capabilities** ▸ **+ App Groups** ▸ `group.com.haliascore.haliatemplates`.
4. Target Membership on `HaliaShare` for: `HaliaAPI.swift`, `Credentials.swift`, `AppGroup.swift`, `ClientRef.swift`.
5. In the target's **Info.plist**, replace `NSExtension` so it uses our class and accepts text/URLs (no storyboard):
   ```xml
   <key>NSExtension</key>
   <dict>
     <key>NSExtensionPointIdentifier</key><string>com.apple.share-services</string>
     <key>NSExtensionPrincipalClass</key><string>$(PRODUCT_MODULE_NAME).ShareViewController</string>
     <key>NSExtensionAttributes</key>
     <dict>
       <key>NSExtensionActivationRule</key>
       <dict>
         <key>NSExtensionActivationSupportsText</key><true/>
         <key>NSExtensionActivationSupportsWebURLWithMaxCount</key><integer>1</integer>
       </dict>
     </dict>
   </dict>
   ```
   (Remove the `NSExtensionMainStoryboard` key Xcode adds — we host SwiftUI from code.)

## 3. CallKit VIP caller-ID  ← written, ready to wire

An incoming call from a graded client reads "Amelia Hart · A*". The host app pulls
`GET /v1/extension/directory`, writes it to the App Group, and reloads the extension; the extension
registers the numbers with CallKit. Only internationally-formatted numbers (`+` / `00`) are included,
since a bare local number can't match an incoming E.164 call. The VIP list is cached **on the
merchant's device** (App Group), wiped on sign-out — the service still stores nothing.

**Files**
- `HaliaCallDirectory/CallDirectoryHandler.swift` → the Call Directory target
- `…/HostApp/CallDirectory.swift` → the **host app** (fetch + save + reload)
- `Shared/DirectoryStore.swift` → **both** the host app and the Call Directory target
- `Shared/HaliaAPI.swift` already has `directory()` + `DirectoryEntry`

**Xcode steps**
1. File ▸ New ▸ Target ▸ **Call Directory Extension**. Name it `HaliaCallDirectory`.
2. Delete Xcode's stub handler; add `CallDirectoryHandler.swift`.
3. **App Groups** on the extension target ▸ `group.com.haliascore.haliatemplates`.
4. Target Membership: `DirectoryStore.swift` and `AppGroup.swift` on **both** the extension and the app;
   `CallDirectory.swift` on the app only.
5. Set `CallDirectory.extensionIdentifier` to the extension's real bundle id (host id + `.HaliaCallDirectory`).
6. Extension **Info.plist**:
   ```xml
   <key>NSExtension</key>
   <dict>
     <key>NSExtensionPointIdentifier</key><string>com.apple.callkit.call-directory</string>
     <key>NSExtensionPrincipalClass</key><string>$(PRODUCT_MODULE_NAME).CallDirectoryHandler</string>
   </dict>
   ```
7. Call `await CallDirectory.refresh()` after each sync (and on sign-out) from the host app. The user
   must enable it once in **Settings ▸ Phone ▸ Call Blocking & Identification ▸ Halia**.

## 4. Build catalogues by browsing — App Intents  ← written, no app to open

Browse the store in Safari, **save products** from the share sheet / Action button, then **build a
catalogue** or **send one to a client** by Siri or Shortcut — the Halia app never opens.

**Backend (shipped + tested):** `POST /v1/extension/catalogue_from_urls` — resolves saved
`…/products/<handle>` URLs to the merchant's own products and mints the same signed catalogue link
the toolbar builds. In [halia/api/extension.py]; tests in [tests/test_extension.py].

**Files** (host app target)
- `…/HostApp/HaliaCatalogueIntents.swift` — the intents: **Save a product**, **Build a catalogue**,
  **Send a product**, **Saved products**, **Clear the list**.
- `…/HostApp/HaliaAppIntents.swift` — the four spoken App Shortcuts (Reach today, Build catalogue,
  Saved products, Clear list).
- `Shared/SavedItemsStore.swift` — the on-device shortlist (App Group). Add to the host-app target.
- `Shared/HaliaAPI.swift` already has `catalogueFromUrls(urls:name:)`.

**Xcode steps:** these need **no new target** — they live in the host app. Just add
`HaliaCatalogueIntents.swift` and `SavedItemsStore.swift` to the `HaliaTemplates` target and build.
App Shortcuts register automatically; find them in Shortcuts, Spotlight and Siri.

**The share-sheet / Action-button "Save to Halia"**: the `SaveItemIntent` takes a URL, so it works
anywhere iOS passes one. Two zero-code ways to reach it while browsing:
- **Action button** (iPhone 15 Pro+): Settings ▸ Action Button ▸ Shortcut ▸ *Save a product to Halia*.
- **Share sheet**: in Shortcuts, make a one-tap shortcut that *Receives URLs from the share sheet* and
  runs *Save a product to Halia*; it then appears under Share ▸ your shortcut on any product page.
- **Send / build** are spoken: "Build a catalogue with Halia", then the returned link chains into
  Messages/WhatsApp. Nothing is stored server-side; the list is on-device and cleared on sign-out.

**The keyboard is the hub.** Whatever App Intents save lands in `SavedItemsStore` (App Group), and the
**keyboard reads it back**: a `🛍 Saved (N)` pill appears in the keyboard's action row, opening a Saved
view where the associate taps a product to insert its link, or **Build catalogue** to drop one
catalogue link into the chat, right where they're composing. So the flow is: save while browsing →
open WhatsApp → Halia keyboard → Saved → Build catalogue. Add `SavedItemsStore.swift` to the
**HaliaKeyboard** target as well (it's already used by the host app and the intents).
