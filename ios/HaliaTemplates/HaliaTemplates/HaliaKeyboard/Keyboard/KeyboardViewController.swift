// Target membership: KEYBOARD EXTENSION ONLY.
//
// The Halia composer. It helps an associate send a personal, on-voice message to a client without
// leaving WhatsApp. Two rows above the content: who the message is for, and five things to do.
//
//   Client bar   "Who is it for?" — type a name and pick from the book, or paste a name or number.
//   Actions      Write · Reply · Pieces · Book · More
//   Content      the templates list by default; a draft to read before it goes in; a shelf of pieces;
//                the days and times for a visit; the longer list of tools behind More.
//
// Offline (no Full Access) the synced templates still insert with one tap. It never reads the
// screen: the client, and any message being replied to, are only what the associate types or copies.
import UIKit

@MainActor
final class KeyboardViewController: UIInputViewController, UITableViewDataSource, UITableViewDelegate,
                                    UICollectionViewDataSource, UICollectionViewDelegateFlowLayout {

    private enum Mode { case templates, write, draft, pieces, saved, book, more, several, name }

    private struct SuggestRow { let id, title, why: String; let price: String?; var on: Bool }
    private struct MoreRow { let title: String; let detail: String?; let symbol: String; let action: () -> Void }

    // Halia palette
    private let brand = UIColor(red: 0.12, green: 0.34, blue: 0.29, alpha: 1) // #1F564A
    private let tint  = UIColor(red: 0.90, green: 0.94, blue: 0.92, alpha: 1) // #E6EFEB
    private let paper = UIColor(red: 0.945, green: 0.945, blue: 0.945, alpha: 1) // #F1F1F1
    private let line  = UIColor(red: 0.89, green: 0.89, blue: 0.89, alpha: 1)    // #E3E3E3

    private let intents: [(String, String)] = [
        ("Hello", "Send a warm, personal hello to reconnect."),
        ("Private preview", "Invite them to a private preview before it opens to everyone."),
        ("New arrival", "Tell them about a new arrival they would love, based on what they buy."),
        ("Follow up", "Follow up warmly on their recent visit or order."),
        ("Thank you", "Thank them personally for a recent purchase."),
        ("Win-back", "A gentle, warm message to reconnect after a quiet spell."),
        ("Offer a time", "Offer a private appointment at the boutique this week. Ask which day and "
                         + "time would suit them. Do not name specific times or dates yourself."),
    ]
    private let refinements: [(String, String)] = [
        ("Warmer", "Rewrite it warmer and more personal."),
        ("Shorter", "Rewrite it shorter and tighter."),
        ("More formal", "Rewrite it a little more formal."),
    ]

    // State
    private var mode: Mode = .templates
    private var burstQueue: BurstStore.Queue?
    private var savedItems: [SavedItemsStore.Item] = []
    private var draftIsHandoff = false
    private var currentRef: ClientRef?
    private var clientName: String?
    private var clientCid: String?
    private var clientEmail: String?
    private var clientPhone: String?
    private var statusText: String?
    private var busy = false
    private var statusLoading = false
    private var lastInserted: String?
    private var lastReplacement: (original: String, polished: String)?
    private var polishedText: String?
    private var pendingOccasion: (label: String, date: String, cid: String)?
    private var bookDay: Date?
    private var bookMinutes: Int?
    private var undoClearTask: Task<Void, Never>?
    private var nameQuery = ""                         // the name being typed for a lookup
    private var nameWork: DispatchWorkItem?
    private var nameHits: [HaliaAPI.Client] = []
    private var nameSearching = false
    private var showingSuggestions = false             // in Pieces: Halia's picks, over the shelf

    private var includeGreeting: Bool {
        get { (AppGroup.defaults.object(forKey: "halia.kb.greeting") as? Bool) ?? true }
        set { AppGroup.defaults.set(newValue, forKey: "halia.kb.greeting") }
    }
    private var includeSignoff: Bool {
        get { (AppGroup.defaults.object(forKey: "halia.kb.signoff") as? Bool) ?? true }
        set { AppGroup.defaults.set(newValue, forKey: "halia.kb.signoff") }
    }
    private var suggestions: [SuggestRow] = []
    private var products: [HaliaAPI.Product] = []
    private var productCartBase: String?
    private var prodCollection: String?
    private var prodSize: String?
    private var prodViewIds: [String] = []
    private var prodCollections: [String] = []
    private var prodSizes: [String] = []
    private var searchQuery = ""
    private var searchWork: DispatchWorkItem?
    private var draftText = ""
    private var draftEnglish: String?
    private var briefSummary: String?
    private var briefUrgency: String?
    private var briefActions: [HaliaAPI.BriefAction] = []
    private var lastThread: [[String: String]]?
    private var cartUrl: String?
    private var cartCount: Int?
    private var pendingCartUrl: String?

    private var templates: [Template] = []
    private var categories: [String] = []
    private var selectedCategory: String?
    private var moreRows: [MoreRow] = []

    // Views
    private let clientBar = UIStackView()
    private let actionScroll = UIScrollView()
    private let actionStack = UIStackView()
    private var actionHeight: NSLayoutConstraint!
    private let chipsScroll = UIScrollView()
    private let chipsStack = UIStackView()
    private var chipsHeight: NSLayoutConstraint!
    private let confirmBar = UIView()
    private var confirmHeight: NSLayoutConstraint!
    private let table = UITableView(frame: .zero, style: .plain)
    private let draftView = UITextView()
    private let grid: UICollectionView = {
        let l = UICollectionViewFlowLayout()
        l.minimumInteritemSpacing = 8
        l.minimumLineSpacing = 12
        l.sectionInset = UIEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        let cv = UICollectionView(frame: .zero, collectionViewLayout: l)
        cv.backgroundColor = .clear
        cv.translatesAutoresizingMaskIntoConstraints = false
        cv.isHidden = true
        return cv
    }()
    private let emptyLabel = UILabel()
    private let cellID = "cell"
    private let bottomBar = UIView()
    private var bottomBarHeight: NSLayoutConstraint!
    private enum BottomKind { case control, keys }
    private var bottomBarKind: BottomKind?
    private var kbHeight: NSLayoutConstraint!
    private static let baseHeight: CGFloat = 384
    private static let keysHeight: CGFloat = 540

    private var filtered: [Template] {
        guard let c = selectedCategory else { return templates }
        if c == Self.recentCat { return recentTemplates }
        if c == Self.forThemCat { return suggestedTemplates }
        return templates.filter { $0.category == c }
    }

    // "For them": the server ranks the merchant's templates for the client just looked up. Shown
    // first and selected automatically, so the right note is one tap, never a scroll.
    private static let forThemCat = "\u{0}for-them"
    private static let recentCat = "\u{0}recent"
    private var suggestedNames: [String] = []
    private var suggestedTemplates: [Template] {
        suggestedNames.compactMap { n in templates.first { $0.name == n } }
    }
    private func applySuggestions(_ names: [String]?) {
        suggestedNames = names ?? []
        if !suggestedNames.isEmpty, mode == .templates { selectedCategory = Self.forThemCat }
        else if selectedCategory == Self.forThemCat { selectedCategory = nil }
        rebuildChips()
        table.reloadData()
    }
    private var recentTemplates: [Template] {
        (AppGroup.defaults.stringArray(forKey: "halia.recentTemplateIds") ?? [])
            .compactMap { id in templates.first { $0.id == id } }
    }
    private func recordRecentTemplate(_ id: String) {
        var list = (AppGroup.defaults.stringArray(forKey: "halia.recentTemplateIds") ?? []).filter { $0 != id }
        list.insert(id, at: 0)
        AppGroup.defaults.set(Array(list.prefix(6)), forKey: "halia.recentTemplateIds")
    }
    private var currentFirstName: String? {
        if let n = clientName?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty {
            return String(n.split(separator: " ").first ?? "")
        }
        let p = currentRef?.provisionalFirstName ?? ""
        return p.isEmpty ? nil : p
    }
    private var selectedCount: Int { suggestions.filter { $0.on }.count }
    private var hasClient: Bool { currentRef != nil }

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = paper
        pinHeight(Self.baseHeight)
        buildClientBar()
        buildActionRow()
        buildChips()
        buildConfirmBar()
        buildTable()
        buildEmptyLabel()
        buildBottomBar()
        buildDraftView()
        buildGrid()
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        reload()
    }

    private func pinHeight(_ h: CGFloat) {
        kbHeight = view.heightAnchor.constraint(equalToConstant: h)
        kbHeight.priority = UILayoutPriority(999)
        kbHeight.isActive = true
    }

    // MARK: - Refresh

    private func reload() {
        templates = TemplateStore.load() + StoreInfoStore.asTemplates()
        burstQueue = BurstStore.load()
        if mode == .several && burstQueue == nil { mode = .templates }
        var seen = Set<String>()
        categories = templates.map { $0.category }.filter { seen.insert($0).inserted }.sorted()
        if let c = selectedCategory, c != Self.recentCat, c != Self.forThemCat, !categories.contains(c) { selectedCategory = nil }
        if mode == .more { moreRows = buildMoreRows() }
        rebuildClientBar()
        rebuildActionRow()
        rebuildChips()
        rebuildConfirmBar()
        rebuildBottomBar()

        let showDraft = (mode == .draft)
        let showGrid = ((mode == .pieces && !showingSuggestions) || mode == .saved) && !products.isEmpty
        let showTable = mode == .templates || (mode == .pieces && showingSuggestions)
            || (mode == .saved && products.isEmpty) || mode == .more || mode == .name
        draftView.isHidden = !showDraft
        draftView.attributedText = draftAttributed()
        grid.isHidden = !showGrid
        table.isHidden = !showTable

        switch mode {
        case .book:
            emptyLabel.text = bookSummary(); emptyLabel.isHidden = false
        case .several:
            emptyLabel.text = burstSummary(); emptyLabel.isHidden = false
        case .write:
            emptyLabel.text = hasClient ? "What kind of message?" : "Say who it is for first."
            emptyLabel.isHidden = false
        case .pieces:
            if showingSuggestions { emptyLabel.isHidden = true }
            else {
                emptyLabel.text = hasFullAccess ? "Nothing here. Try another word, or clear the filters."
                    : "Turn on Full Access in Settings to browse pieces."
                emptyLabel.isHidden = !products.isEmpty || busy
            }
        case .name:
            emptyLabel.text = nameQuery.isEmpty ? "Type their name, or paste a name or number."
                : (nameSearching ? "Looking…" : "No one by that name in your book.")
            emptyLabel.isHidden = !nameHits.isEmpty
        case .templates:
            emptyLabel.text = "Open the Halia app and connect to bring your templates here."
            emptyLabel.isHidden = !templates.isEmpty
        default:
            emptyLabel.isHidden = true
        }
        grid.reloadData()
        table.reloadData()
    }

    // MARK: - Client bar

    private func buildClientBar() {
        clientBar.axis = .horizontal
        clientBar.spacing = 8
        clientBar.alignment = .center
        clientBar.translatesAutoresizingMaskIntoConstraints = false
        clientBar.isLayoutMarginsRelativeArrangement = true
        clientBar.layoutMargins = UIEdgeInsets(top: 6, left: 12, bottom: 6, right: 12)
        view.addSubview(clientBar)
        NSLayoutConstraint.activate([
            clientBar.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            clientBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            clientBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            clientBar.heightAnchor.constraint(equalToConstant: 48),
        ])
    }

    private func rebuildClientBar() {
        clientBar.arrangedSubviews.forEach { $0.removeFromSuperview() }
        if !hasFullAccess {
            clientBar.addArrangedSubview(mutedLabel("Turn on Full Access in Settings to personalise"))
            return
        }
        if lastInserted != nil {
            clientBar.addArrangedSubview(pillButton("Undo", symbol: "arrow.uturn.backward", filled: false) { [weak self] in self?.undoInsert() })
        }
        if mode != .several, let q = burstQueue, q.current != nil {
            clientBar.addArrangedSubview(pillButton("Several · \(q.index + 1) of \(q.items.count)", symbol: "person.2", filled: true) { [weak self] in
                guard let self else { return }; self.mode = .several; self.reload()
            })
        }
        if let s = statusText {
            if statusLoading { clientBar.addArrangedSubview(PixelLoader()) }
            let l = mutedLabel(s)
            l.textColor = statusLoading ? .label : .secondaryLabel
            clientBar.addArrangedSubview(l)
            return
        }
        if mode == .name {
            clientBar.addArrangedSubview(fieldView(text: nameQuery, placeholder: "Who is it for?", symbol: "person.crop.circle") { [weak self] in
                self?.leaveNameMode()
            })
            return
        }
        guard hasClient else {
            let b = fieldView(text: "", placeholder: "Who is it for?", symbol: "person.crop.circle", clear: nil)
            b.addAction(UIAction { [weak self] _ in self?.enterNameMode() }, for: .touchUpInside)
            clientBar.addArrangedSubview(b)
            return
        }
        let label = mutedLabel("For \(clientName ?? currentRef?.value ?? "client")")
        label.textColor = brand
        label.font = .systemFont(ofSize: 14, weight: .semibold)
        clientBar.addArrangedSubview(label)
        clientBar.addArrangedSubview(iconButton("xmark") { [weak self] in self?.clearClient() })
    }

    /// The name field on the client bar: a rounded box that shows what has been typed so far.
    private func fieldView(text: String, placeholder: String, symbol: String, clear: (() -> Void)?) -> UIButton {
        let b = UIButton(type: .system)
        var c = UIButton.Configuration.plain()
        c.image = UIImage(systemName: symbol, withConfiguration: UIImage.SymbolConfiguration(pointSize: 13, weight: .medium))
        c.imagePadding = 7
        c.baseForegroundColor = text.isEmpty ? .secondaryLabel : .label
        c.contentInsets = NSDirectionalEdgeInsets(top: 8, leading: 12, bottom: 8, trailing: 12)
        c.background.backgroundColor = .systemBackground
        c.background.cornerRadius = 12
        c.background.strokeColor = line
        c.background.strokeWidth = 1
        var t = AttributedString(text.isEmpty ? placeholder : text)
        t.font = .systemFont(ofSize: 14, weight: text.isEmpty ? .regular : .semibold)
        c.attributedTitle = t
        b.configuration = c
        b.contentHorizontalAlignment = .leading
        b.setContentHuggingPriority(.defaultLow, for: .horizontal)
        if let clear {
            let x = UIButton(type: .system)
            x.setImage(UIImage(systemName: "xmark.circle.fill"), for: .normal)
            x.tintColor = .tertiaryLabel
            x.translatesAutoresizingMaskIntoConstraints = false
            x.addAction(UIAction { _ in clear() }, for: .touchUpInside)
            b.addSubview(x)
            NSLayoutConstraint.activate([
                x.trailingAnchor.constraint(equalTo: b.trailingAnchor, constant: -8),
                x.centerYAnchor.constraint(equalTo: b.centerYAnchor),
                x.widthAnchor.constraint(equalToConstant: 28),
            ])
        }
        return b
    }

    // MARK: - Who is it for (typed, picked from the book, or pasted)

    private func enterNameMode() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        nameQuery = ""; nameHits = []
        mode = .name; setStatus(nil); reload()
    }

    private func leaveNameMode() {
        nameWork?.cancel(); nameQuery = ""; nameHits = []
        mode = .templates; reload()
    }

    private func typeName(_ s: String) { nameQuery += s; afterNameEdit() }
    private func deleteName() { guard !nameQuery.isEmpty else { return }; nameQuery.removeLast(); afterNameEdit() }
    private func afterNameEdit() {
        rebuildClientBar()
        nameWork?.cancel()
        let q = nameQuery.trimmingCharacters(in: .whitespaces)
        nameSearching = !q.isEmpty
        let work = DispatchWorkItem { [weak self] in self?.runNameSearch(q) }
        nameWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: work)
    }

    private func runNameSearch(_ q: String) {
        guard mode == .name else { return }
        guard !q.isEmpty else { nameHits = []; nameSearching = false; reload(); return }
        Task {
            do {
                let hits = try await HaliaAPI.current.clients(q: q)
                guard mode == .name, q == nameQuery.trimmingCharacters(in: .whitespaces) else { return }
                nameHits = hits
            } catch { nameHits = [] }
            nameSearching = false
            reload()
        }
    }

    /// Return on the name keys: the first match, else look the typed name up as written.
    private func findTypedName() {
        if let first = nameHits.first { pick(first); return }
        let q = nameQuery.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        adopt(ClientRef(kind: .name, value: q), name: q)
    }

    private func pick(_ c: HaliaAPI.Client) {
        let ref = c.cid.map { ClientRef(kind: .cid, value: $0) } ?? ClientRef(kind: .name, value: c.name)
        clientEmail = c.email; clientPhone = c.phone
        adopt(ref, name: c.name)
    }

    private func useCopiedClient() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        guard let ref = ClientClassifier.classify(UIPasteboard.general.string ?? "") else {
            flash("Copy their name or number first"); return
        }
        adopt(ref, name: ref.kind == .name ? ref.value : nil)
    }

    /// Make this the client on the bar, then fill in what the book knows about them.
    private func adopt(_ ref: ClientRef, name: String?) {
        nameWork?.cancel(); nameQuery = ""; nameHits = []
        currentRef = ref
        clientName = name
        clientCid = ref.kind == .cid ? ref.value : nil
        if ref.kind != .cid { clientEmail = nil; clientPhone = nil }
        cartUrl = nil; cartCount = nil
        mode = .templates; suggestions = []; draftText = ""; showingSuggestions = false
        setStatus("Looking up…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.lookup(ref)
                if let n = res.name, !n.isEmpty { clientName = n }
                if let e = res.email, !e.isEmpty { clientEmail = e }
                if let ph = res.phone, !ph.isEmpty { clientPhone = ph }
                applySuggestions(res.suggested)
                if let cid = res.cid, !cid.isEmpty { clientCid = cid }
                if let u = res.cart?.url, !u.isEmpty { cartUrl = u; cartCount = res.cart?.count }
            } catch { /* keep the ref; personalisation still works by name */ }
            setStatus(nil); reload()
        }
    }

    private func clearClient() {
        currentRef = nil; clientName = nil; clientCid = nil; clientEmail = nil; clientPhone = nil; cartUrl = nil; cartCount = nil
        applySuggestions(nil)
        mode = .templates; suggestions = []; draftText = ""; pendingCartUrl = nil; showingSuggestions = false
        setStatus(nil); reload()
    }

    /// Needs a client: go and ask who, rather than doing nothing.
    private func requireClient() -> Bool {
        if hasClient { return true }
        enterNameMode(); return false
    }

    // MARK: - Action row

    private func buildActionRow() {
        configureScroll(actionScroll, stack: actionStack)
        actionHeight = actionScroll.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([
            actionScroll.topAnchor.constraint(equalTo: clientBar.bottomAnchor),
            actionScroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            actionScroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            actionHeight,
        ])
    }

    private func setActions(_ show: Bool) {
        actionHeight.constant = show ? 46 : 0
        actionScroll.isHidden = !show
    }

    private func back(_ title: String = "Back") -> UIButton {
        pillButton(title, symbol: "chevron.left", filled: false) { [weak self] in self?.backToTemplates() }
    }

    private func rebuildActionRow() {
        actionStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        switch mode {
        case .templates:
            guard hasFullAccess else { setActions(false); return }
            setActions(true)
            actionStack.addArrangedSubview(pillButton("Write", symbol: "pencil.line", filled: true) { [weak self] in self?.enterWrite() })
            actionStack.addArrangedSubview(pillButton("Reply", symbol: "arrowshape.turn.up.left", filled: false) { [weak self] in self?.replyToCopied() })
            actionStack.addArrangedSubview(pillButton("Pieces", symbol: "bag", filled: false) { [weak self] in self?.enterPieces() })
            actionStack.addArrangedSubview(pillButton("Book", symbol: "calendar", filled: false) { [weak self] in self?.enterBook() })
            actionStack.addArrangedSubview(pillButton("More", symbol: "ellipsis", filled: false) { [weak self] in self?.enterMore() })

        case .write:
            setActions(true)
            actionStack.addArrangedSubview(back())
            for (label, instruction) in intents {
                actionStack.addArrangedSubview(pillButton(label, filled: false) { [weak self] in
                    self?.startDraft(instruction: instruction, thread: nil)
                })
            }

        case .draft:
            setActions(true)
            actionStack.addArrangedSubview(back())
            actionStack.addArrangedSubview(pillButton("Insert", symbol: "text.insert", filled: true) { [weak self] in self?.insertDraft() })
            for (label, mod) in refinements {
                actionStack.addArrangedSubview(pillButton(label, filled: false) { [weak self] in self?.refine(mod) })
            }

        case .pieces:
            setActions(true)
            if showingSuggestions {
                actionStack.addArrangedSubview(pillButton("Shelf", symbol: "chevron.left", filled: false) { [weak self] in
                    guard let self else { return }; self.showingSuggestions = false; self.reload()
                })
                actionStack.addArrangedSubview(pillButton("Send as catalogue (\(selectedCount))", symbol: "link", filled: true) { [weak self] in self?.sendCatalogue() })
                actionStack.addArrangedSubview(pillButton("Pay link (\(selectedCount))", symbol: "creditcard", filled: false) { [weak self] in self?.sendCartLink() })
            } else {
                actionStack.addArrangedSubview(back())
                actionStack.addArrangedSubview(searchFieldView())
                if hasClient {
                    actionStack.addArrangedSubview(pillButton("For \(currentFirstName ?? "them")", symbol: "sparkles", filled: true) { [weak self] in self?.suggestPieces() })
                }
            }

        case .saved:
            setActions(true)
            actionStack.addArrangedSubview(back())
            actionStack.addArrangedSubview(pillButton("Send as catalogue (\(savedItems.count))", symbol: "link", filled: true) { [weak self] in self?.buildCatalogueFromSaved() })
            actionStack.addArrangedSubview(pillButton("Pay link", symbol: "creditcard", filled: false) { [weak self] in self?.buildCartLinkFromSaved() })
            actionStack.addArrangedSubview(pillButton("Clear", filled: false) { [weak self] in self?.clearSaved() })

        case .book:
            setActions(true)
            actionStack.addArrangedSubview(back())
            if bookDay != nil && bookTimes.isEmpty { actionStack.addArrangedSubview(mutedLabel("Closed that day")) }
            for slot in bookTimes {
                actionStack.addArrangedSubview(togglePill(Self.timeLabel(slot), on: bookMinutes == slot) { [weak self] in
                    guard let self else { return }
                    self.bookMinutes = (self.bookMinutes == slot) ? nil : slot
                    self.rebuildActionRow(); self.rebuildConfirmBar(); self.reload()
                })
            }

        case .more:
            setActions(true)
            actionStack.addArrangedSubview(back())

        case .several:
            setActions(true)
            actionStack.addArrangedSubview(back())
            if burstQueue?.current != nil {
                actionStack.addArrangedSubview(pillButton("Insert", symbol: "text.insert", filled: true) { [weak self] in self?.burstInsert() })
                actionStack.addArrangedSubview(pillButton("Skip", filled: false) { [weak self] in self?.burstSkip() })
            } else {
                actionStack.addArrangedSubview(pillButton("Done", filled: true) { [weak self] in self?.burstDone() })
            }

        case .name:
            setActions(true)
            actionStack.addArrangedSubview(pillButton("Paste a name or number", symbol: "doc.on.clipboard", filled: false) { [weak self] in self?.useCopiedClient() })
        }
    }

    private func enterWrite() {
        guard requireClient() else { return }
        mode = .write; reload()
    }

    // MARK: - More: the longer list of tools

    private func enterMore() {
        mode = .more; reload()
    }

    private func buildMoreRows() -> [MoreRow] {
        var rows: [MoreRow] = []
        rows.append(MoreRow(title: "Polish what I typed", detail: "Rewrites the message in the house voice", symbol: "wand.and.stars") { [weak self] in self?.polishTyped() })
        if polishedText != nil {
            rows.append(MoreRow(title: "Adjust the polish", detail: "Warmer, shorter or more formal", symbol: "slider.horizontal.3") { [weak self] in self?.adjustPolished() })
        }
        if hasClient {
            rows.append(MoreRow(title: "Remember what they said", detail: "Copy their message first; it goes on their record", symbol: "bookmark") { [weak self] in self?.rememberCopied() })
            if cartUrl != nil {
                let n = (cartCount ?? 0) > 0 ? " · \(cartCount!) item\(cartCount == 1 ? "" : "s")" : ""
                rows.append(MoreRow(title: "Nudge their basket", detail: "They left something at checkout" + n, symbol: "basket") { [weak self] in self?.nudgeBasket() })
            }
            if let occ = pendingOccasion {
                rows.append(MoreRow(title: "Follow up before the \(occ.label)", detail: occ.date, symbol: "bell") { [weak self] in self?.followUpOccasion(occ) })
            }
            if clientCid != nil {
                rows.append(MoreRow(title: "Mark as contacted", detail: "So the team sees who is looking after them", symbol: "checkmark.circle") { [weak self] in self?.markContacted() })
            }
            rows.append(MoreRow(title: "Note for the team", detail: "A short handover about them, for a colleague", symbol: "person.2") { [weak self] in self?.handoff() })
        }
        let savedN = SavedItemsStore.count
        if savedN > 0 {
            rows.append(MoreRow(title: "Saved pieces", detail: "\(savedN) saved while browsing", symbol: "bag") { [weak self] in self?.enterSaved() })
        }
        rows.append(MoreRow(title: "Greeting", detail: includeGreeting ? "On. Templates open with “Dear …,”" : "Off. Templates start mid-conversation", symbol: includeGreeting ? "checkmark.square" : "square") { [weak self] in
            guard let self else { return }; self.includeGreeting.toggle(); self.reload()
        })
        rows.append(MoreRow(title: "Sign-off", detail: includeSignoff ? "On. Templates end with your sign-off" : "Off. Templates end on the message", symbol: includeSignoff ? "checkmark.square" : "square") { [weak self] in
            guard let self else { return }; self.includeSignoff.toggle(); self.reload()
        })
        return rows
    }

    // MARK: - Team handoff (a note ABOUT the client, for a colleague; never says "hidden VIP")

    private func handoff() {
        guard requireClient() else { return }
        startDraft(instruction:
            "Write a SHORT internal note for a colleague, not a message to the client. Say who this "
            + "client is, what they want, and the next step, so a teammate can help. Colleague-to-"
            + "colleague tone. Do not use the phrase \"hidden VIP\", and do not mention any grade or score.",
            thread: nil, handoff: true)
    }

    private func scrubInternal(_ text: String) -> String {
        var out = text
        for phrase in ["hidden vip", "hidden vic"] {
            while let r = out.range(of: phrase, options: .caseInsensitive) {
                out.replaceSubrange(r, with: "VIP")
            }
        }
        return out
    }

    private func draftAttributed() -> NSAttributedString {
        let body: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 15), .foregroundColor: UIColor.label]
        let muted: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 13), .foregroundColor: UIColor.secondaryLabel]
        let out = NSMutableAttributedString()
        if let sum = briefSummary, !sum.isEmpty {
            out.append(NSAttributedString(string: sum + "\n\n", attributes: muted))
        }
        out.append(NSAttributedString(string: draftText, attributes: body))
        if let en = draftEnglish, !en.isEmpty {
            out.append(NSAttributedString(string: "\n\nIn English: " + en, attributes: muted))
        }
        return out
    }

    // MARK: - Draft (personal message, read before it goes in)

    private func startDraft(instruction: String, thread: [[String: String]]?,
                            cartUrl: String? = nil, handoff: Bool = false) {
        guard let ref = currentRef, !busy else { return }
        pendingCartUrl = cartUrl
        draftIsHandoff = handoff
        busy = true; setStatus(handoff ? "Writing the note…" : "Writing…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.draft(ref, channel: handoff ? "internal" : "whatsapp",
                                                           instruction: instruction, thread: thread)
                if let n = res.name, !n.isEmpty { clientName = n }
                if let d = res.draft, !d.isEmpty {
                    clearBrief()
                    draftText = handoff ? scrubInternal(d) : d
                    draftEnglish = handoff ? nil : res.english
                    lastThread = thread; mode = .draft; setStatus(nil)
                } else { setStatus("Nothing came back. Try again.") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func nudgeBasket() {
        guard cartUrl != nil else { return }
        startDraft(instruction: "They started an order but did not finish checking out (an open "
                   + "basket). Write a warm, personal message offering to help them complete it or "
                   + "answer any questions, gently and without pressure. Do not mention amounts.",
                   thread: nil, cartUrl: cartUrl)
    }

    private func replyToCopied() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        guard requireClient() else { return }
        let msg = (UIPasteboard.general.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty else { flash("Copy their message first, then tap Reply"); return }
        let thread = [["from": "them", "text": msg]]
        guard let ref = currentRef, !busy else { return }
        busy = true; setStatus("Reading…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.brief(ref, channel: "whatsapp", thread: thread)
                if let n = res.name, !n.isEmpty { clientName = n }
                if let r = res.reply, !r.isEmpty {
                    draftText = r; draftEnglish = res.english
                    briefSummary = res.summary; briefUrgency = res.urgency; briefActions = res.actions ?? []
                    lastThread = thread; pendingCartUrl = nil; draftIsHandoff = false
                    mode = .draft; setStatus(nil)
                } else { setStatus("Nothing came back. Try again.") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    // MARK: - Book a visit

    private var bookTimes: [Int] { HoursStore.slots(on: bookDay ?? Date()) }
    private static let bookDays = 90

    private static func timeLabel(_ minutes: Int) -> String {
        String(format: "%02d:%02d", minutes / 60, minutes % 60)
    }

    private static func dayLabel(_ day: Date, offset: Int) -> String {
        if offset == 0 { return "Today" }
        if offset == 1 { return "Tomorrow" }
        let f = DateFormatter()
        f.dateFormat = offset < 7 ? "EEE d" : "d MMM"
        return f.string(from: day)
    }

    private func bookSummary() -> String {
        guard let day = bookDay else { return "Pick a day, then a time." }
        let f = DateFormatter(); f.dateFormat = "EEEE d MMMM"
        guard let mins = bookMinutes else { return f.string(from: day) + " · pick a time" }
        return f.string(from: day) + " at " + Self.timeLabel(mins)
    }

    private func enterBook() {
        guard requireClient() else { return }
        guard clientCid != nil else { flash("They are not in your book yet"); return }
        bookDay = nil; bookMinutes = nil
        mode = .book; setStatus(nil); reload()
    }

    private func confirmBooking() {
        guard let cid = clientCid, let day = bookDay, let mins = bookMinutes, !busy else { return }
        let cal = Calendar.current
        guard let at = cal.date(byAdding: .minute, value: mins, to: cal.startOfDay(for: day)) else { return }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        iso.timeZone = TimeZone.current
        busy = true; setStatus("Booking…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.bookAppointment(cid: cid, when: iso.string(from: at),
                                                                     place: "", clientName: clientName ?? "",
                                                                     clientEmail: clientEmail ?? "")
                if let msg = res.links?.message, !msg.isEmpty {
                    mode = .templates; bookDay = nil; bookMinutes = nil
                    insertUndoable(msg)
                    setStatus(nil); flash("Booked")
                } else { setStatus("Could not book that time") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    // MARK: - Remember

    private func rememberCopied() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        guard let ref = currentRef, !busy else { return }
        let msg = (UIPasteboard.general.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty else { flash("Copy their message first"); return }
        busy = true; setStatus("Saving…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.remember(text: msg, ref: ref)
                if let sum = res.summary, !sum.isEmpty {
                    setStatus(nil); flash("Saved: " + sum)
                    if let occ = res.occasion, let d = occ.date, !d.isEmpty, let cid = res.cid ?? clientCid {
                        pendingOccasion = (occ.label ?? "occasion", d, cid)
                    }
                } else { setStatus("Nothing to remember in that message") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; mode = .templates; reload()
        }
    }

    private func weekBefore(_ iso: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
        guard let d = f.date(from: iso) else { return iso }
        var cal = Calendar(identifier: .iso8601); cal.firstWeekday = 2
        let monday = cal.date(from: cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: d)) ?? d
        let target = cal.date(byAdding: .day, value: -7, to: monday) ?? monday
        return f.string(from: max(target, Date()))
    }

    private func followUpOccasion(_ occ: (label: String, date: String, cid: String)) {
        let due = weekBefore(occ.date)
        Task {
            do {
                try await HaliaAPI.current.captureFollowUp(customerId: occ.cid, note: "\(occ.label) on \(occ.date)", due: due)
                pendingOccasion = nil; flash("Follow-up set"); mode = .templates; reload()
            } catch { flash("Could not reach Halia") }
        }
    }

    private func clearBrief() {
        briefSummary = nil; briefUrgency = nil; briefActions = []; draftEnglish = nil
    }

    private func briefPills() -> [UIButton] {
        var out: [UIButton] = []
        if let u = briefUrgency, !u.isEmpty { out.append(togglePill(u.capitalized, on: true) {}) }
        var seen = Set<String>()
        for a in briefActions {
            let kind = a.kind ?? "", label = (a.label ?? "").lowercased()
            var pill: UIButton?
            if kind == "contacted", clientCid != nil, seen.insert("contacted").inserted {
                pill = pillButton("Mark as contacted", filled: false) { [weak self] in self?.markContacted() }
            } else if kind == "catalogue", seen.insert("catalogue").inserted {
                pill = pillButton("Pieces for them", filled: false) { [weak self] in self?.suggestPieces() }
            } else if kind == "pipeline", let cid = clientCid, seen.insert("pipeline").inserted {
                let note = a.label ?? "Follow up"
                pill = pillButton("Follow up", filled: false) { [weak self] in self?.followUp(cid: cid, note: note) }
            } else if kind == "advice", label.contains("basket") || label.contains("checkout"), cartUrl != nil,
                      seen.insert("basket").inserted {
                pill = pillButton("Nudge their basket", filled: false) { [weak self] in self?.nudgeBasket() }
            }
            if let p = pill { out.append(p) }
        }
        return out
    }

    private func followUp(cid: String, note: String) {
        Task {
            do { try await HaliaAPI.current.captureFollowUp(customerId: cid, note: note); flash("Follow-up set") }
            catch { flash("Could not reach Halia") }
        }
    }

    private func refine(_ modifier: String) {
        guard mode == .draft, !busy, !draftText.isEmpty else { return }
        startDraft(instruction: modifier + " Current draft to adjust: " + draftText,
                   thread: lastThread, cartUrl: pendingCartUrl, handoff: draftIsHandoff)
    }

    private func insertDraft() {
        guard !draftText.isEmpty else { return }
        var text = draftText
        if let url = pendingCartUrl, !url.isEmpty { text += "\n\n" + url }
        insertUndoable(text)
        mode = .templates; draftText = ""; lastThread = nil; pendingCartUrl = nil; clearBrief(); reload()
    }

    // MARK: - Pieces: the shelf, and Halia's picks for this client

    private func enterPieces() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings to browse pieces"); return }
        mode = .pieces; products = []; searchQuery = ""; showingSuggestions = false
        prodCollection = nil; prodSize = nil; prodViewIds = []
        reload()
        runProductSearch("")
    }

    private func suggestPieces() {
        guard let ref = currentRef, !busy else { return }
        busy = true; setStatus("Choosing pieces…", loading: true)
        Task {
            do {
                let picks = try await HaliaAPI.current.suggest(ref, instruction: "")
                suggestions = picks.map { SuggestRow(id: $0.productId, title: $0.title,
                                                     why: $0.why, price: $0.priceText, on: true) }
                if suggestions.isEmpty { setStatus("Nothing stood out for them. Browse the shelf instead.") }
                else { mode = .pieces; showingSuggestions = true; setStatus(nil) }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func sendCatalogue() {
        let ids = suggestions.filter { $0.on }.map { $0.id }
        guard !ids.isEmpty else { flash("Tick at least one piece"); return }
        guard !busy else { return }
        busy = true; setStatus("Making the catalogue…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.catalogue(productIds: ids, name: clientName,
                                                               email: clientEmail ?? "", phone: clientPhone ?? "")
                insertUndoable(url)
                mode = .templates; suggestions = []; showingSuggestions = false; setStatus(nil)
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func sendViewAsSelection() {
        guard !prodViewIds.isEmpty else { flash("Nothing on this shelf"); return }
        guard !busy else { return }
        busy = true; setStatus("Making the selection…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.catalogue(productIds: prodViewIds, name: clientName,
                                                               email: clientEmail ?? "", phone: clientPhone ?? "")
                insertUndoable(url)
                mode = .templates; setStatus(nil)
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func sendCartLink() {
        let ids = suggestions.filter { $0.on }.map { $0.id }
        guard !ids.isEmpty else { flash("Tick at least one piece"); return }
        guard !busy else { return }
        busy = true; setStatus("Making the pay link…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.cartLink(productIds: ids)
                insertUndoable(url)
                mode = .templates; suggestions = []; showingSuggestions = false; setStatus(nil)
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func backToTemplates() {
        clearBrief()
        mode = .templates; suggestions = []; products = []; draftText = ""; pendingCartUrl = nil
        bookDay = nil; bookMinutes = nil; showingSuggestions = false
        searchQuery = ""; searchWork?.cancel(); reload()
    }

    // MARK: - Saved pieces (what App Intents saved while browsing)

    private func enterSaved() {
        savedItems = SavedItemsStore.load()
        products = []; productCartBase = nil
        mode = .saved
        reload()
        if !AppGroup.defaults.bool(forKey: "halia.savedHint") {
            AppGroup.defaults.set(true, forKey: "halia.savedHint")
            flash("Tap to send, hold to remove")
        }
        guard hasFullAccess, !savedItems.isEmpty else { return }
        let urls = savedItems.map { $0.url }
        Task {
            do {
                let (prods, base) = try await HaliaAPI.current.productsFromUrls(urls)
                guard mode == .saved else { return }
                products = prods; productCartBase = base
                reload()
            } catch { /* keep the text list */ }
        }
    }

    private func buildCatalogueFromSaved() {
        let urls = savedItems.map { $0.url }
        guard !urls.isEmpty else { flash("Nothing saved yet"); return }
        guard hasFullAccess else { flash("Turn on Full Access to build a catalogue"); return }
        guard !busy else { return }
        busy = true; setStatus("Making the catalogue…", loading: true)
        Task {
            do {
                let r = try await HaliaAPI.current.catalogueFromUrls(urls: urls, name: clientName ?? "",
                                                                     email: clientEmail ?? "", phone: clientPhone ?? "")
                if r.url.isEmpty { setStatus("None of the saved pieces are in this store") }
                else { insertUndoable(r.url); mode = .templates; setStatus(nil); flash("Catalogue inserted") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func buildCartLinkFromSaved() {
        let urls = savedItems.map { $0.url }
        guard !urls.isEmpty else { flash("Nothing saved yet"); return }
        guard hasFullAccess else { flash("Turn on Full Access to make a pay link"); return }
        guard !busy else { return }
        busy = true; setStatus("Making the pay link…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.cartLinkFromUrls(urls: urls)
                if url.isEmpty { setStatus("None of the saved pieces can be bought right now") }
                else { insertUndoable(url); mode = .templates; setStatus(nil); flash("Pay link inserted") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func clearSaved() {
        SavedItemsStore.clear()
        savedItems = []
        mode = .templates
        reload()
    }

    private func savedDisplayName(_ it: SavedItemsStore.Item) -> String {
        if let t = it.title, !t.trimmingCharacters(in: .whitespaces).isEmpty { return t }
        let path = it.url.split(separator: "?").first.map(String.init) ?? it.url
        let tail = path.split(separator: "/").last.map(String.init) ?? it.url
        let name = tail.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
        return name.isEmpty ? it.url : name.capitalized
    }

    // MARK: - Product search (live, from the keys)

    private func afterSearchEdit() {
        rebuildActionRow()
        searchWork?.cancel()
        let q = searchQuery
        let work = DispatchWorkItem { [weak self] in self?.runProductSearch(q) }
        searchWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: work)
    }

    private func typeSearch(_ s: String) { searchQuery += s; afterSearchEdit() }
    private func deleteSearch() { guard !searchQuery.isEmpty else { return }; searchQuery.removeLast(); afterSearchEdit() }
    private func clearSearch() { searchQuery = ""; afterSearchEdit() }

    private func runProductSearch(_ q: String) {
        guard !busy else { return }
        busy = true; setStatus(q.isEmpty ? "Loading the shelf…" : "Searching…", loading: true)
        Task {
            do {
                let view = try await HaliaAPI.current.searchProducts(
                    q, collection: prodCollection ?? "", size: prodSize ?? "")
                products = view.products; productCartBase = view.cartBase
                prodViewIds = view.ids
                if !view.collections.isEmpty { prodCollections = view.collections }
                if !view.sizes.isEmpty { prodSizes = view.sizes }
                setStatus(nil)
                rebuildChips()
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
            if mode == .pieces && searchQuery != q { runProductSearch(searchQuery) }
        }
    }

    // MARK: - Several clients, from inside the chat

    private func burstSummary() -> String {
        guard let q = burstQueue else { return "" }
        guard let it = q.current else {
            return "\(q.sent) sent" + (q.skipped > 0 ? ", \(q.skipped) skipped" : "") + ". Tap Done."
        }
        var lines = ["\(q.index + 1) of \(q.items.count) · \(it.name)" + (it.grade.isEmpty ? "" : " · \(it.grade)"),
                     it.consentLine]
        if let w = it.warnLine { lines.append(w) }
        lines.append("Open their chat, then Insert. Insert marks them as contacted.")
        lines.append("")
        lines.append(it.body)
        return lines.joined(separator: "\n")
    }

    private func burstInsert() {
        guard var q = burstQueue, let it = q.current else { return }
        insertUndoable(it.body)
        q.items[q.index].status = "sent"; q.index += 1
        BurstStore.save(q); burstQueue = q
        if hasFullAccess {
            Task { try? await HaliaAPI.current.logContacted(
                cid: it.cid, clientName: it.name, reason: "Sent \(q.template) from the keyboard", quiet: true) }
        }
        flash(q.current == nil ? "Inserted, that was the last" : "Inserted, next")
        reload()
    }

    private func burstSkip() {
        guard var q = burstQueue, q.current != nil else { return }
        q.items[q.index].status = "skipped"; q.index += 1
        BurstStore.save(q); burstQueue = q
        reload()
    }

    private func burstDone() {
        if let q = burstQueue, q.sent > 0, hasFullAccess {
            Task { await HaliaAPI.current.burstDone(n: q.sent, template: q.template, channel: q.channel) }
        }
        BurstStore.clear(); burstQueue = nil
        mode = .templates
        reload()
    }

    private func markContacted() {
        guard let cid = clientCid else { flash("They are not in your book yet"); return }
        guard !busy else { return }
        busy = true; setStatus("Marking…", loading: true)
        Task {
            do {
                _ = try await HaliaAPI.current.logContacted(cid: cid, clientName: clientName,
                                                            reason: "Messaged from the keyboard")
                busy = false; flash("Marked as contacted")
            } catch {
                busy = false
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            mode = .templates; reload()
        }
    }

    // MARK: - Chips (categories, days, the shelf's filters)

    private func buildChips() {
        configureScroll(chipsScroll, stack: chipsStack)
        chipsHeight = chipsScroll.heightAnchor.constraint(equalToConstant: 44)
        NSLayoutConstraint.activate([
            chipsScroll.topAnchor.constraint(equalTo: actionScroll.bottomAnchor),
            chipsScroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            chipsScroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            chipsHeight,
        ])
    }

    private func buildConfirmBar() {
        confirmBar.translatesAutoresizingMaskIntoConstraints = false
        confirmBar.backgroundColor = .clear
        view.addSubview(confirmBar)
        confirmHeight = confirmBar.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([
            confirmBar.topAnchor.constraint(equalTo: chipsScroll.bottomAnchor),
            confirmBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            confirmBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            confirmHeight,
        ])
    }

    private func rebuildConfirmBar() {
        confirmBar.subviews.forEach { $0.removeFromSuperview() }
        let ready = mode == .book && bookDay != nil && bookMinutes != nil
        confirmHeight.constant = ready ? 50 : 0
        confirmBar.isHidden = !ready
        guard ready else { return }
        let b = pillButton("Book", symbol: "calendar.badge.checkmark", filled: true) { [weak self] in self?.confirmBooking() }
        b.translatesAutoresizingMaskIntoConstraints = false
        confirmBar.addSubview(b)
        NSLayoutConstraint.activate([
            b.leadingAnchor.constraint(equalTo: confirmBar.leadingAnchor, constant: 12),
            b.trailingAnchor.constraint(equalTo: confirmBar.trailingAnchor, constant: -12),
            b.topAnchor.constraint(equalTo: confirmBar.topAnchor, constant: 4),
            b.heightAnchor.constraint(equalToConstant: 38),
        ])
    }

    private func setChips(_ show: Bool) {
        chipsHeight.constant = show ? 44 : 0
        chipsScroll.isHidden = !show
    }

    private func rebuildChips() {
        chipsStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        switch mode {
        case .book:
            setChips(true)
            let cal = Calendar.current
            for offset in 0..<Self.bookDays {
                guard let day = cal.date(byAdding: .day, value: offset, to: cal.startOfDay(for: Date())) else { continue }
                let on = bookDay.map { cal.isDate($0, inSameDayAs: day) } ?? false
                chipsStack.addArrangedSubview(togglePill(Self.dayLabel(day, offset: offset), on: on) { [weak self] in
                    guard let self else { return }
                    self.bookDay = on ? nil : day
                    if !self.bookTimes.contains(self.bookMinutes ?? -1) { self.bookMinutes = nil }
                    self.rebuildChips(); self.rebuildActionRow()
                    self.rebuildConfirmBar(); self.reload()
                })
            }
        case .pieces where !showingSuggestions:
            setChips(true)
            if !prodViewIds.isEmpty {
                chipsStack.addArrangedSubview(pillButton("Send all \(prodViewIds.count)", symbol: "link", filled: true) { [weak self] in
                    self?.sendViewAsSelection()
                })
            }
            for c in prodCollections.prefix(40) {
                chipsStack.addArrangedSubview(togglePill(c, on: prodCollection == c) { [weak self] in
                    guard let self else { return }
                    self.prodCollection = (self.prodCollection == c) ? nil : c
                    self.rebuildChips(); self.runProductSearch(self.searchQuery)
                })
            }
            for z in prodSizes.prefix(40) {
                chipsStack.addArrangedSubview(togglePill("Size \(z)", on: prodSize == z) { [weak self] in
                    guard let self else { return }
                    self.prodSize = (self.prodSize == z) ? nil : z
                    self.rebuildChips(); self.runProductSearch(self.searchQuery)
                })
            }
        case .draft:
            let pills = briefPills()
            setChips(!pills.isEmpty)
            pills.forEach { chipsStack.addArrangedSubview($0) }
        case .templates:
            setChips(!templates.isEmpty)
            guard !templates.isEmpty else { return }
            if !suggestedTemplates.isEmpty {
                chipsStack.addArrangedSubview(chip(title: "For \(currentFirstName ?? "them")", value: Self.forThemCat, symbol: "sparkles"))
            }
            if !recentTemplates.isEmpty {
                chipsStack.addArrangedSubview(chip(title: "Recent", value: Self.recentCat, symbol: "clock"))
            }
            chipsStack.addArrangedSubview(chip(title: "All", value: nil, symbol: nil))
            for c in categories { chipsStack.addArrangedSubview(chip(title: c, value: c, symbol: nil)) }
        default:
            setChips(false)
        }
    }

    private func chip(title: String, value: String?, symbol: String?) -> UIButton {
        pillButton(title, symbol: symbol, filled: value == selectedCategory) { [weak self] in
            self?.selectedCategory = value
            self?.rebuildChips()
            self?.table.reloadData()
        }
    }

    // MARK: - Table

    private func buildTable() {
        table.translatesAutoresizingMaskIntoConstraints = false
        table.dataSource = self
        table.delegate = self
        table.backgroundColor = .clear
        table.tintColor = brand
        table.register(UITableViewCell.self, forCellReuseIdentifier: cellID)
        view.addSubview(table)
        NSLayoutConstraint.activate([
            table.topAnchor.constraint(equalTo: confirmBar.bottomAnchor),
            table.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            table.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        let lp = UILongPressGestureRecognizer(target: self, action: #selector(handleTableLongPress(_:)))
        lp.minimumPressDuration = 0.45
        table.addGestureRecognizer(lp)
    }

    /// Hold a template to copy it instead of inserting it.
    @objc private func handleTableLongPress(_ g: UILongPressGestureRecognizer) {
        guard g.state == .began else { return }
        guard let ip = table.indexPathForRow(at: g.location(in: table)) else { return }
        if mode == .templates, ip.row < filtered.count {
            Clipboard.put(filtered[ip.row].ready(firstName: currentFirstName, greeting: includeGreeting, signoff: includeSignoff))
            flash("Copied")
        } else if mode == .saved, ip.row < savedItems.count {
            Clipboard.put(savedItems[ip.row].url)
            flash("Copied")
        }
    }

    private func buildDraftView() {
        draftView.translatesAutoresizingMaskIntoConstraints = false
        draftView.isEditable = false
        draftView.isSelectable = true
        draftView.backgroundColor = .clear
        draftView.font = .systemFont(ofSize: 15)
        draftView.textColor = .label
        draftView.textContainerInset = UIEdgeInsets(top: 12, left: 14, bottom: 12, right: 14)
        draftView.isHidden = true
        view.addSubview(draftView)
        NSLayoutConstraint.activate([
            draftView.topAnchor.constraint(equalTo: table.topAnchor),
            draftView.leadingAnchor.constraint(equalTo: table.leadingAnchor),
            draftView.trailingAnchor.constraint(equalTo: table.trailingAnchor),
            draftView.bottomAnchor.constraint(equalTo: table.bottomAnchor),
        ])
    }

    private func buildEmptyLabel() {
        emptyLabel.translatesAutoresizingMaskIntoConstraints = false
        emptyLabel.numberOfLines = 0
        emptyLabel.textAlignment = .center
        emptyLabel.textColor = .secondaryLabel
        emptyLabel.font = .systemFont(ofSize: 14)
        emptyLabel.isHidden = true
        view.addSubview(emptyLabel)
        NSLayoutConstraint.activate([
            emptyLabel.centerXAnchor.constraint(equalTo: table.centerXAnchor),
            emptyLabel.centerYAnchor.constraint(equalTo: table.centerYAnchor),
            emptyLabel.leadingAnchor.constraint(equalTo: table.leadingAnchor, constant: 28),
            emptyLabel.trailingAnchor.constraint(equalTo: table.trailingAnchor, constant: -28),
        ])
    }

    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        switch mode {
        case .pieces: return showingSuggestions ? suggestions.count : 0
        case .saved: return savedItems.count
        case .more: return moreRows.count
        case .name: return nameHits.count
        default: return filtered.count
        }
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: cellID)
        cell.backgroundColor = .clear
        cell.textLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        cell.detailTextLabel?.textColor = .secondaryLabel
        cell.detailTextLabel?.numberOfLines = 1
        cell.accessoryType = .none
        cell.imageView?.tintColor = brand

        switch mode {
        case .pieces:
            let s = suggestions[indexPath.row]
            cell.textLabel?.text = s.title
            cell.detailTextLabel?.text = [s.price, s.why].compactMap { $0 }.joined(separator: "  ·  ")
            cell.accessoryType = s.on ? .checkmark : .none
        case .saved:
            let it = savedItems[indexPath.row]
            cell.textLabel?.text = savedDisplayName(it)
            cell.detailTextLabel?.text = it.url
        case .more:
            let r = moreRows[indexPath.row]
            cell.textLabel?.text = r.title
            cell.detailTextLabel?.text = r.detail
            cell.imageView?.image = UIImage(systemName: r.symbol, withConfiguration: UIImage.SymbolConfiguration(pointSize: 15, weight: .medium))
        case .name:
            let c = nameHits[indexPath.row]
            cell.textLabel?.text = c.name
            cell.detailTextLabel?.text = c.grade.isEmpty ? nil : "Grade \(c.grade)"
        default:
            let t = filtered[indexPath.row]
            cell.textLabel?.text = t.name
            cell.detailTextLabel?.text = t.preview
        }
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        switch mode {
        case .pieces:
            guard indexPath.row < suggestions.count else { return }
            suggestions[indexPath.row].on.toggle()
            tableView.reloadRows(at: [indexPath], with: .none)
            rebuildActionRow()
        case .saved:
            insertUndoable(savedItems[indexPath.row].url); flash("Link inserted")
        case .more:
            guard indexPath.row < moreRows.count else { return }
            moreRows[indexPath.row].action()
        case .name:
            guard indexPath.row < nameHits.count else { return }
            pick(nameHits[indexPath.row])
        default:
            let t = filtered[indexPath.row]
            insertUndoable(t.ready(firstName: currentFirstName, greeting: includeGreeting, signoff: includeSignoff))
            recordRecentTemplate(t.id)
            rebuildChips()
            if selectedCategory == Self.recentCat { table.reloadData() }
        }
    }

    func tableView(_ tableView: UITableView,
                   trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath) -> UISwipeActionsConfiguration? {
        guard mode == .saved, indexPath.row < savedItems.count else { return nil }
        let remove = UIContextualAction(style: .destructive, title: "Remove") { [weak self] _, _, done in
            guard let self = self, indexPath.row < self.savedItems.count else { done(false); return }
            SavedItemsStore.remove(url: self.savedItems[indexPath.row].url)
            self.savedItems = SavedItemsStore.load()
            if self.savedItems.isEmpty { self.mode = .templates }
            self.reload()
            done(true)
        }
        return UISwipeActionsConfiguration(actions: [remove])
    }

    // MARK: - Product grid

    private func buildGrid() {
        grid.dataSource = self
        grid.delegate = self
        grid.register(ProductCell.self, forCellWithReuseIdentifier: ProductCell.id)
        view.addSubview(grid)
        NSLayoutConstraint.activate([
            grid.topAnchor.constraint(equalTo: table.topAnchor),
            grid.leadingAnchor.constraint(equalTo: table.leadingAnchor),
            grid.trailingAnchor.constraint(equalTo: table.trailingAnchor),
            grid.bottomAnchor.constraint(equalTo: table.bottomAnchor),
        ])
        let lp = UILongPressGestureRecognizer(target: self, action: #selector(handleGridLongPress(_:)))
        lp.minimumPressDuration = 0.45
        grid.addGestureRecognizer(lp)
    }

    @objc private func handleGridLongPress(_ g: UILongPressGestureRecognizer) {
        guard g.state == .began, mode == .saved else { return }
        guard let ip = grid.indexPathForItem(at: g.location(in: grid)), ip.item < products.count else { return }
        SavedItemsStore.remove(handle: products[ip.item].handle ?? "")
        products.remove(at: ip.item)
        savedItems = SavedItemsStore.load()
        if products.isEmpty && savedItems.isEmpty { mode = .templates }
        reload()
        flash("Removed")
    }

    func collectionView(_ collectionView: UICollectionView, numberOfItemsInSection section: Int) -> Int {
        products.count
    }

    func collectionView(_ collectionView: UICollectionView, cellForItemAt indexPath: IndexPath) -> UICollectionViewCell {
        let cell = collectionView.dequeueReusableCell(withReuseIdentifier: ProductCell.id, for: indexPath) as! ProductCell
        guard indexPath.item < products.count else { return cell }
        let p = products[indexPath.item]
        cell.cap.text = p.title
        let token = indexPath.item + 1
        cell.img.image = nil
        cell.img.tag = token
        if let url = p.imageURL { ThumbnailLoader.shared.load(url, into: cell.img, token: token) }
        return cell
    }

    func collectionView(_ collectionView: UICollectionView, didSelectItemAt indexPath: IndexPath) {
        guard indexPath.item < products.count else { return }
        let p = products[indexPath.item]
        // A keyboard cannot attach a file, so the photo goes to the clipboard for one paste.
        guard let url = p.imageURL else { shareProductLink(p); return }
        guard hasFullAccess else { flash("Turn on Full Access to send photos"); return }
        setStatus("Copying the photo…", loading: true)
        Task {
            do {
                let (data, _) = try await URLSession.shared.data(from: url)
                if let img = UIImage(data: data) {
                    Clipboard.put(image: img)
                    flash("Photo copied. Hold the chat and tap Paste to send it.")
                } else { shareProductLink(p) }
            } catch { shareProductLink(p) }
        }
    }

    private func shareProductLink(_ p: HaliaAPI.Product) {
        if let link = p.shareLink(cartBase: productCartBase), !link.isEmpty {
            insertUndoable(link); flash("Link inserted")
        } else {
            flash("Nothing to send for that piece")
        }
    }

    func collectionView(_ collectionView: UICollectionView, layout collectionViewLayout: UICollectionViewLayout,
                        sizeForItemAt indexPath: IndexPath) -> CGSize {
        let cols: CGFloat = 3
        let w = floor((collectionView.bounds.width - 24 - 8 * (cols - 1)) / cols)
        return CGSize(width: max(60, w), height: max(60, w) + 20)
    }

    // MARK: - Bottom bar (a control row, or letter keys that type into a field of ours)

    private func buildBottomBar() {
        bottomBar.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(bottomBar)
        bottomBarHeight = bottomBar.heightAnchor.constraint(equalToConstant: 50)
        NSLayoutConstraint.activate([
            bottomBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            bottomBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            bottomBar.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
            bottomBarHeight,
            table.bottomAnchor.constraint(equalTo: bottomBar.topAnchor),
        ])
        rebuildBottomBar()
    }

    private var wantsKeys: Bool { mode == .name || (mode == .pieces && !showingSuggestions) }

    private func rebuildBottomBar() {
        let kind: BottomKind = wantsKeys ? .keys : .control
        guard bottomBarKind != kind || (kind == .keys && bottomBarModeBuilt != mode) else { return }
        bottomBarKind = kind; bottomBarModeBuilt = mode
        bottomBar.subviews.forEach { $0.removeFromSuperview() }
        if kind == .keys {
            bottomBarHeight.constant = 198
            kbHeight?.constant = Self.keysHeight
            buildLetterKeys(into: bottomBar)
        } else {
            bottomBarHeight.constant = 50
            kbHeight?.constant = Self.baseHeight
            buildControlRow(into: bottomBar)
        }
    }
    private var bottomBarModeBuilt: Mode?

    private func buildControlRow(into bar: UIView) {
        let row = UIStackView()
        row.axis = .horizontal
        row.spacing = 6
        row.translatesAutoresizingMaskIntoConstraints = false
        row.isLayoutMarginsRelativeArrangement = true
        row.layoutMargins = UIEdgeInsets(top: 6, left: 6, bottom: 6, right: 6)
        bar.addSubview(row)

        let globe = key(symbol: "globe") { [weak self] in self?.advanceToNextInputMode() }
        let space = key("space") { [weak self] in self?.textDocumentProxy.insertText(" ") }
        let del   = key(symbol: "delete.left") { [weak self] in self?.textDocumentProxy.deleteBackward() }
        let ret   = key("return") { [weak self] in self?.textDocumentProxy.insertText("\n") }
        [globe, del, ret].forEach { $0.widthAnchor.constraint(equalToConstant: 64).isActive = true }
        [globe, space, del, ret].forEach { row.addArrangedSubview($0) }

        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: bar.leadingAnchor),
            row.trailingAnchor.constraint(equalTo: bar.trailingAnchor),
            row.topAnchor.constraint(equalTo: bar.topAnchor),
            row.bottomAnchor.constraint(equalTo: bar.bottomAnchor),
        ])
    }

    /// Letter keys that type into our own field (a name, or the shelf search), never into the chat.
    private func buildLetterKeys(into bar: UIView) {
        let col = UIStackView(arrangedSubviews: [
            keyRow("qwertyuiop"),
            keyRow("asdfghjkl"),
            keyRow("zxcvbnm"),
            functionRow(),
        ])
        col.axis = .vertical
        col.spacing = 6
        col.distribution = .fillEqually
        col.translatesAutoresizingMaskIntoConstraints = false
        col.isLayoutMarginsRelativeArrangement = true
        col.layoutMargins = UIEdgeInsets(top: 5, left: 4, bottom: 5, right: 4)
        bar.addSubview(col)
        NSLayoutConstraint.activate([
            col.leadingAnchor.constraint(equalTo: bar.leadingAnchor),
            col.trailingAnchor.constraint(equalTo: bar.trailingAnchor),
            col.topAnchor.constraint(equalTo: bar.topAnchor),
            col.bottomAnchor.constraint(equalTo: bar.bottomAnchor),
        ])
    }

    private func typeKey(_ s: String) { if mode == .name { typeName(s) } else { typeSearch(s) } }
    private func deleteKey() { if mode == .name { deleteName() } else { deleteSearch() } }

    private func keyRow(_ letters: String) -> UIStackView {
        let s = UIStackView()
        s.axis = .horizontal
        s.spacing = 5
        s.distribution = .fillEqually
        for ch in letters {
            let letter = String(ch)
            s.addArrangedSubview(key(letter) { [weak self] in self?.typeKey(letter) })
        }
        return s
    }

    private func functionRow() -> UIStackView {
        let s = UIStackView()
        s.axis = .horizontal
        s.spacing = 5
        s.distribution = .fill
        let globe = key(symbol: "globe") { [weak self] in self?.advanceToNextInputMode() }
        let space = key("space") { [weak self] in self?.typeKey(" ") }
        let del   = key(symbol: "delete.left") { [weak self] in self?.deleteKey() }
        globe.widthAnchor.constraint(equalToConstant: 58).isActive = true
        del.widthAnchor.constraint(equalToConstant: 58).isActive = true
        [globe, space, del].forEach { s.addArrangedSubview($0) }
        if mode == .name {
            let find = key("Find") { [weak self] in self?.findTypedName() }
            find.widthAnchor.constraint(equalToConstant: 64).isActive = true
            find.backgroundColor = brand
            find.setTitleColor(.white, for: .normal)
            s.addArrangedSubview(find)
        }
        return s
    }

    /// The shelf's search box on the action row: what has been typed, with a clear control.
    private func searchFieldView() -> UIView {
        let box = fieldView(text: searchQuery, placeholder: "Search the shelf", symbol: "magnifyingglass",
                            clear: searchQuery.isEmpty ? nil : { [weak self] in self?.clearSearch() })
        box.isUserInteractionEnabled = !searchQuery.isEmpty
        box.widthAnchor.constraint(greaterThanOrEqualToConstant: 200).isActive = true
        return box
    }

    // MARK: - Helpers

    private func configureScroll(_ scroll: UIScrollView, stack: UIStackView) {
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.showsHorizontalScrollIndicator = false
        view.addSubview(scroll)
        stack.axis = .horizontal
        stack.spacing = 8
        stack.alignment = .center
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.isLayoutMarginsRelativeArrangement = true
        stack.layoutMargins = UIEdgeInsets(top: 5, left: 12, bottom: 5, right: 12)
        scroll.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor),
            stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
            stack.heightAnchor.constraint(equalTo: scroll.frameLayoutGuide.heightAnchor),
        ])
    }

    private func setStatus(_ s: String?, loading: Bool = false) {
        statusText = s
        statusLoading = loading && (s != nil)
        rebuildClientBar()
        rebuildActionRow()
    }

    private func flash(_ s: String) {
        setStatus(s)
        Task {
            try? await Task.sleep(nanoseconds: 1_800_000_000)
            if statusText == s { setStatus(nil) }
        }
    }

    /// Insert into the chat and offer Undo for a moment, in case the wrong thing went in.
    private func insertUndoable(_ text: String) {
        guard !text.isEmpty else { return }
        textDocumentProxy.insertText(text)
        lastInserted = text
        rebuildClientBar()
        undoClearTask?.cancel()
        undoClearTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard let self = self, !Task.isCancelled else { return }
            self.lastInserted = nil
            self.rebuildClientBar()
        }
    }

    private func undoInsert() {
        guard let t = lastInserted else { return }
        for _ in 0..<t.count { textDocumentProxy.deleteBackward() }
        if let r = lastReplacement, r.polished == t {
            textDocumentProxy.insertText(r.original)
            lastReplacement = nil; polishedText = nil
            lastInserted = nil; undoClearTask?.cancel(); rebuildClientBar(); rebuildActionRow()
            flash("Restored what you typed")
            return
        }
        lastInserted = nil
        undoClearTask?.cancel()
        flash("Removed")
    }

    // MARK: - Polish (the associate's own message, in the house voice)

    private func readWholeField() -> String {
        let proxy = textDocumentProxy
        var guardCount = 0
        while let after = proxy.documentContextAfterInput, !after.isEmpty, guardCount < 40 {
            proxy.adjustTextPosition(byCharacterOffset: after.count); guardCount += 1
        }
        var text = ""
        var moved = 0
        guardCount = 0
        while let before = proxy.documentContextBeforeInput, !before.isEmpty, text.count < 4000, guardCount < 40 {
            text = before + text
            proxy.adjustTextPosition(byCharacterOffset: -before.count); moved += before.count; guardCount += 1
        }
        if moved > 0 { proxy.adjustTextPosition(byCharacterOffset: moved) }
        return text
    }

    private func polishTyped() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        guard !busy else { return }
        let original = readWholeField()
        guard !original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { flash("Type a message first"); return }
        busy = true; setStatus("Polishing…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.polish(text: original, ref: currentRef,
                                                            greeting: includeGreeting, signoff: includeSignoff)
                if let t = res.text, !t.isEmpty {
                    replaceUndoable(original: original, with: t)
                    polishedText = t
                    setStatus(nil); flash("Polished")
                } else { setStatus("Nothing came back") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; mode = .templates; reload()
        }
    }

    private func replaceUndoable(original: String, with polished: String) {
        _ = readWholeField()
        for _ in 0..<min(original.count, 4000) { textDocumentProxy.deleteBackward() }
        lastReplacement = (original, polished)
        insertUndoable(polished)
    }

    private func adjustPolished() {
        guard let t = polishedText, !t.isEmpty else { return }
        draftText = t; lastThread = nil; pendingCartUrl = nil; draftIsHandoff = false
        mode = .draft; reload()
    }

    private func mutedLabel(_ text: String) -> UILabel {
        let l = UILabel()
        l.text = text
        l.font = .systemFont(ofSize: 13.5)
        l.textColor = .secondaryLabel
        l.numberOfLines = 1
        l.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return l
    }

    /// A pill: a short title, an optional symbol before it, filled when it is the main thing to do.
    private func pillButton(_ title: String, symbol: String? = nil, filled: Bool, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        var c = UIButton.Configuration.filled()
        c.baseBackgroundColor = filled ? brand : tint
        c.baseForegroundColor = filled ? .white : brand
        c.cornerStyle = .fixed
        c.background.cornerRadius = 12
        c.contentInsets = NSDirectionalEdgeInsets(top: 7, leading: 13, bottom: 7, trailing: 13)
        var t = AttributedString(title)
        t.font = .systemFont(ofSize: 13, weight: .semibold)
        c.attributedTitle = t
        if let symbol {
            c.image = UIImage(systemName: symbol, withConfiguration: UIImage.SymbolConfiguration(pointSize: 11, weight: .semibold))
            c.imagePadding = 5
        }
        b.configuration = c
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return b
    }

    /// A pill that reads as on or off.
    private func togglePill(_ title: String, on: Bool, action: @escaping () -> Void) -> UIButton {
        let b = pillButton(title, symbol: on ? "checkmark" : nil, filled: on, action: action)
        if !on { b.alpha = 0.7 }
        return b
    }

    private func iconButton(_ systemName: String, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        b.setImage(UIImage(systemName: systemName), for: .normal)
        b.tintColor = brand
        b.widthAnchor.constraint(equalToConstant: 34).isActive = true
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return b
    }

    private func key(_ title: String, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        b.setTitle(title, for: .normal)
        b.titleLabel?.font = .systemFont(ofSize: 15, weight: .medium)
        b.setTitleColor(.label, for: .normal)
        b.backgroundColor = UIColor.systemBackground.withAlphaComponent(0.9)
        b.layer.cornerRadius = 8
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return b
    }

    private func key(symbol: String, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        b.setImage(UIImage(systemName: symbol, withConfiguration: UIImage.SymbolConfiguration(pointSize: 16, weight: .medium)), for: .normal)
        b.tintColor = .label
        b.backgroundColor = UIColor.systemBackground.withAlphaComponent(0.9)
        b.layer.cornerRadius = 8
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return b
    }
}
