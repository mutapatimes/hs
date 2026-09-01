# iOS app extensions: what exists and what is left to do by hand

All the extension targets are created and wired in `HaliaTemplates.xcodeproj`. Nothing here needs
Xcode's "New Target" wizard any more.

| Target               | What it is                                   | Bundle id                                          |
|----------------------|----------------------------------------------|----------------------------------------------------|
| `HaliaKeyboard`      | Custom keyboard (templates, drafts, products) | `com.haliascore.HaliaTemplates.HaliaKeyboard`      |
| `HaliaShare`         | Share sheet: "Send with Halia", capture a shared contact | `com.haliascore.HaliaTemplates.HaliaShare` |
| `HaliaCallDirectory` | CallKit caller ID for graded clients          | `com.haliascore.HaliaTemplates.HaliaCallDirectory` |
| `HaliaIMessage`      | Messages drawer: the desk (client, templates, pieces, draft, book) | `com.haliascore.HaliaTemplates.HaliaIMessage` |

The "Reach today" widget was dropped from the product (2026-08-17). Its backend endpoint and the
Siri/Shortcuts App Intents in the host app remain; there is no widget target.

Shared facts: App Group `group.com.haliascore.haliatemplates` on every target, deployment target iOS 18.5,
Team `4PJ32C8P4K`, automatic signing. Shared code lives in `HaliaTemplates/HaliaKeyboard/Shared/` and each
extension compiles its own copy through a membership exception set on the `HaliaTemplates` folder group
(see `project.pbxproj`, section `PBXFileSystemSynchronizedBuildFileExceptionSet`).

## Verify from the command line

```
cd ios/HaliaTemplates
xcodebuild -list -project HaliaTemplates.xcodeproj
xcodebuild build -project HaliaTemplates.xcodeproj -scheme HaliaTemplates \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO
```

One caution learned adding HaliaIMessage: a target's folder is attached through
`fileSystemSynchronizedGroups`, and the same reference line appears in the main group's children.
Inserting by text match hits both, and the neighbouring extension then compiles your folder too
("Multiple commands produce …Info.plist"). Check each target's `fileSystemSynchronizedGroups`
lists only its own folder.

A second caution, learned when App Store Connect rejected build 5: an iMessage extension must ship
its own icon, and the app's icon does not stand in. `scripts/build_brand_marks.py` generates
`HaliaIMessage/Assets.xcassets/iMessage App Icon.stickersiconset` (eight 4:3 sizes plus 1024x1024
and 1024x768 marketing), and both HaliaIMessage configurations set
`ASSETCATALOG_COMPILER_APPICON_NAME = "iMessage App Icon"`. The set must be a `.stickersiconset`,
not an `.appiconset`, and the metadata keys are fussy: the four small `universal` entries need
`"platform": "ios"` beside the scale, and the 1024x768 marketing entry needs both. Get any of it
wrong and actool assigns nothing, silently drops `MSMessagesExtensionStoreIconName`, and the
upload fails with codes 90649 and 90642 long after the build succeeded. To check before archiving:

```
plutil -extract MSMessagesExtensionStoreIconName raw \
  <DerivedData>/…/HaliaTemplates.app/PlugIns/HaliaIMessage.appex/Info.plist
```

## The human bits (need an Apple account or a device)

1. **App IDs and the App Group in the developer portal.** With automatic signing, selecting the Team on
   each target registers the three extension App IDs and attaches the App Group. If a TestFlight upload
   fails with "failed to register bundle identifier", add the App IDs by hand at developer.apple.com and
   tick App Groups on each.
2. **Keyboard on a device:** Settings → General → Keyboard → Keyboards → Add New Keyboard → Halia, then
   Allow Full Access (needed to reach the network).
3. **Caller ID on a device:** run the app once (it writes the directory and asks CallKit to reload), then
   Settings → Phone → Call Blocking & Identification → enable Halia. The simulator builds it but does not
   run it.
4. **Share sheet:** share a contact, a name or a product URL from Contacts, Safari or Shopify; Halia
   appears in the sheet. If it is missing, tap More and switch it on.
5. **Messages drawer:** in a conversation, tap the apps row beside the text field and choose Halia.

## Adding a shared file to an extension later

Select the file in the Project Navigator, open the File Inspector (⌥⌘1) and tick the target under
Target Membership. Xcode adds it to that target's exception set; no other project edits are needed.
