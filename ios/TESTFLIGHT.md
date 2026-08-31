# Sending a build to TestFlight

The Mac Halia is developed on holds an **Apple Development** certificate only, so an App Store
build has to be made from your Xcode (or from a machine with an Apple Distribution certificate and
an App Store Connect API key). Everything else is ready: the build number is bumped and
`ios/HaliaTemplates/ExportOptions.plist` carries the upload settings.

## From Xcode (the usual way)

1. Open `ios/HaliaTemplates/HaliaTemplates.xcodeproj`.
2. Scheme **HaliaTemplates**, destination **Any iOS Device (arm64)**.
3. **Product → Archive**. All four targets build: the app, the keyboard, Share, CallKit.
4. In the Organizer: **Distribute App → TestFlight & App Store → Upload**, automatic signing.
5. App Store Connect processes it in five to fifteen minutes, then it appears in TestFlight.
   Answer the export-compliance question once (Halia uses only standard HTTPS).

## From the command line

Needs an Apple Distribution certificate in the login keychain and an App Store Connect API key
saved at `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8`:

```
cd ios/HaliaTemplates
xcodebuild -project HaliaTemplates.xcodeproj -scheme HaliaTemplates \
  -destination 'generic/platform=iOS' -archivePath build/Halia.xcarchive archive
xcodebuild -exportArchive -archivePath build/Halia.xcarchive \
  -exportOptionsPlist ExportOptions.plist -exportPath build/export \
  -allowProvisioningUpdates \
  -authenticationKeyPath ~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8 \
  -authenticationKeyID <KEYID> -authenticationKeyIssuerID <ISSUER-UUID>
```

## Version numbers

`MARKETING_VERSION` is the version people see (1.0); `CURRENT_PROJECT_VERSION` is the build
number and must rise with every upload. Bump it with:

```
sed -i '' 's/CURRENT_PROJECT_VERSION = 4;/CURRENT_PROJECT_VERSION = 5;/g' \
  ios/HaliaTemplates/HaliaTemplates.xcodeproj/project.pbxproj
```

## Trying it before TestFlight

Two faster routes than an archive:

- **A simulator**, which needs nothing from Apple:
  `xcodebuild build -project HaliaTemplates.xcodeproj -scheme HaliaTemplates -sdk iphonesimulator
  -destination 'id=<booted sim id>' -derivedDataPath build/sim CODE_SIGNING_ALLOWED=NO`, then
  `xcrun simctl install <sim id> build/sim/.../HaliaTemplates.app`. The keyboard and the Messages
  app both appear.
- **Your own iPhone**, using the development certificate already on this Mac: plug it in, unlock
  it, trust the Mac, then
  `xcodebuild -project HaliaTemplates.xcodeproj -scheme HaliaTemplates -destination 'id=<device
  id>' -allowProvisioningUpdates build`. `xcrun devicectl list devices` shows the id.

## What is in build 5

Keyboard: Polish what I typed, the brief behind Reply, Remember, replies in the client's language,
and Book a visit (day and time pills, then the client's invitation into the chat). App: the
Appointments section with the client's message and an .ics to share, birthdays, your results.
Messages: the Halia app in the drawer, which opens on your catalogue and sends a selection the
client can pick from.
