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
