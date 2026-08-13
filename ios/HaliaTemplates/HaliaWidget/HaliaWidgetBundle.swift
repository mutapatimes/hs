// Target membership: HaliaWidget (the widget extension) ONLY. This is the extension's @main entry.
import WidgetKit
import SwiftUI

@main
struct HaliaWidgetBundle: WidgetBundle {
    var body: some Widget {
        TodayWidget()
    }
}
