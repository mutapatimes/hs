// Target membership: HaliaCallDirectory (the Call Directory extension) ONLY.
// Also add Shared/DirectoryStore.swift and Shared/AppGroup.swift to this target, and give it the
// App Group group.com.haliascore.haliatemplates.
//
// VIP caller-ID: when iOS asks the extension to (re)load, we read the list the host app wrote to the
// App Group and register each graded client so an incoming call shows "Amelia Hart · A*". We do a
// full replace each time (isIncremental is ignored) — correct and simple for a small VIP set.
import Foundation
import CallKit

class CallDirectoryHandler: CXCallDirectoryProvider {

    override func beginRequest(with context: CXCallDirectoryExtensionContext) {
        context.delegate = self
        // Entries arrive already de-duplicated and sorted ascending, which addIdentificationEntry requires.
        for entry in DirectoryStore.load() {
            context.addIdentificationEntry(
                withNextSequentialPhoneNumber: CXCallDirectoryPhoneNumber(entry.number),
                label: entry.label)
        }
        context.completeRequest()
    }
}

extension CallDirectoryHandler: CXCallDirectoryExtensionContextDelegate {
    func requestFailed(for extensionContext: CXCallDirectoryExtensionContext, withError error: Error) {
        // iOS retries later; nothing to persist here.
    }
}
