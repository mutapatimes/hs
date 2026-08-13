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

## 2. Share Extension  ← source coming next

"Send with Halia" from Photos / Safari / Shopify / Contacts: share a product image or a customer, and
Halia looks them up and drafts a message. Reuses `HaliaAPI.lookup` + `draft`. Needs a Share Extension
target, the App Group, and the shared files; activation rule accepts images, URLs, and text.

## 3. CallKit VIP caller-ID  ← source coming next

`GET /v1/extension/directory` → a **Call Directory** extension that loads graded clients so an incoming
call from a top client reads "Amelia Hart · A*". The host app fetches the directory, writes it to the
App Group, and calls `CXCallDirectoryManager.reloadExtension`. Only numbers stored internationally
(with `+`/`00`) are included, since a bare local number can't match an incoming E.164 call. This is the
one surface where a small list of VIP numbers is cached **on the merchant's device** (App Group), wiped
on sign-out — the service itself still stores nothing.
