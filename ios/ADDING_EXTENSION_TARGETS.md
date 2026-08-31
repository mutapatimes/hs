# iOS app extensions: what exists and what is left to do by hand

All the extension targets are created and wired in `HaliaTemplates.xcodeproj`. Nothing here needs
Xcode's "New Target" wizard any more.

| Target               | What it is                                   | Bundle id                                          |
|----------------------|----------------------------------------------|----------------------------------------------------|
| `HaliaKeyboard`      | Custom keyboard (templates, drafts, products) | `com.haliascore.HaliaTemplates.HaliaKeyboard`      |
| `HaliaShare`         | Share sheet: "Send with Halia", capture a shared contact | `com.haliascore.HaliaTemplates.HaliaShare` |
| `HaliaCallDirectory` | CallKit caller ID for graded clients          | `com.haliascore.HaliaTemplates.HaliaCallDirectory` |
| `HaliaIMessage`      | Messages drawer: build a selection, send the link | `com.haliascore.HaliaTemplates.HaliaIMessage` |

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
   An iMessage app also needs its own `iMessage App Icon` asset before an App Store submission
   (1024 marketing plus the messages sizes); TestFlight builds carry a placeholder until then.

## Adding a shared file to an extension later

Select the file in the Project Navigator, open the File Inspector (⌥⌘1) and tick the target under
Target Membership. Xcode adds it to that target's exception set; no other project edits are needed.
