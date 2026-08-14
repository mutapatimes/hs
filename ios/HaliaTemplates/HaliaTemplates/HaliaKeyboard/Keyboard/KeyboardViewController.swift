// Target membership: KEYBOARD EXTENSION ONLY.
//
// The Halia composer. It helps an associate send a personal, on-voice message to a VIP without
// leaving WhatsApp. No grade here on purpose: the point is the message.
//
// Layers:
//   1. Offline (no Full Access): synced templates, one tap to insert. House catalogue via the
//      {catalog_link} template.
//   2. With Full Access: copy the client's name or number, tap "Use copied client". Then templates
//      fill with their real name; the intent chips draft a personal message; "Reply" drafts a reply
//      to a message you copied; a draft can be refined (warmer / shorter / more formal) before it
//      goes in; "Suggest pieces" recommends products as a branded catalogue link; and "Mark
//      contacted" logs the outreach to the shared team pipeline.
//
// It never reads the WhatsApp screen. The client, and any message being replied to, are only what
// you copy.
import UIKit

@MainActor
final class KeyboardViewController: UIInputViewController, UITableViewDataSource, UITableViewDelegate,
                                    UICollectionViewDataSource, UICollectionViewDelegateFlowLayout {

    private enum Mode { case templates, suggestions, draft, products, saved }
    private enum Audience { case client, team }   // write to the client, or to the team about them

    private struct SuggestRow { let id, title, why: String; let price: String?; var on: Bool }

    // Halia palette
    private let brand = UIColor(red: 0.12, green: 0.34, blue: 0.29, alpha: 1) // #1F564A
    private let tint  = UIColor(red: 0.90, green: 0.94, blue: 0.92, alpha: 1) // #E6EFEB
    private let paper = UIColor(red: 0.95, green: 0.94, blue: 0.91, alpha: 1) // #F1EFE9

    private let intents: [(String, String)] = [
        ("Hello", "Send a warm, personal hello to reconnect."),
        ("Private preview", "Invite them to a private preview before it opens to everyone."),
        ("New arrival", "Tell them about a new arrival they would love, based on what they buy."),
        ("Follow up", "Follow up warmly on their recent visit or order."),
        ("Thank you", "Thank them personally for a recent purchase."),
        ("Win-back", "A gentle, warm message to reconnect after a quiet spell."),
    ]
    private let refinements: [(String, String)] = [
        ("Warmer", "Rewrite it warmer and more personal."),
        ("Shorter", "Rewrite it shorter and tighter."),
        ("More formal", "Rewrite it a little more formal."),
    ]

    // State
    private var mode: Mode = .templates
    private var savedItems: [SavedItemsStore.Item] = []   // products saved while browsing (via App Intents)
    private var audience: Audience = .client
    private var draftIsHandoff = false
    private var currentRef: ClientRef?
    private var clientName: String?
    private var clientCid: String?
    private var statusText: String?
    private var busy = false
    private var statusLoading = false
    private var loadStart: Date?
    private var elapsedTimer: Timer?
    private weak var elapsedLabel: UILabel?
    private var draftShownAnimated = false
    private var suggestions: [SuggestRow] = []
    private var products: [HaliaAPI.Product] = []
    private var productCartBase: String?
    private var searchQuery = ""              // the live product-search text, typed on the in-keyboard keys
    private var searchWork: DispatchWorkItem? // debounces live search as you type
    private var draftText = ""
    private var lastThread: [[String: String]]?
    private var cartUrl: String?         // the client's open basket (recovery link), if any
    private var cartCount: Int?
    private var pendingCartUrl: String?  // append this recovery link when the current draft is inserted

    private var templates: [Template] = []
    private var categories: [String] = []
    private var selectedCategory: String?

    // Views
    private let clientBar = UIStackView()
    private let actionScroll = UIScrollView()
    private let actionStack = UIStackView()
    private var actionHeight: NSLayoutConstraint!
    private let chipsScroll = UIScrollView()
    private let chipsStack = UIStackView()
    private var chipsHeight: NSLayoutConstraint!
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
    private let bottomBar = UIView()          // holds either the control row or the search keyboard
    private var bottomBarHeight: NSLayoutConstraint!
    private var bottomBarMode: Mode?          // only rebuild the bottom bar when the mode changes
    private var kbHeight: NSLayoutConstraint! // the keyboard's overall height (taller while searching)

    private var filtered: [Template] {
        guard let c = selectedCategory else { return templates }
        return templates.filter { $0.category == c }
    }
    private var currentFirstName: String? {
        if let n = clientName?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty {
            return String(n.split(separator: " ").first ?? "")
        }
        let p = currentRef?.provisionalFirstName ?? ""
        return p.isEmpty ? nil : p
    }
    private var selectedCount: Int { suggestions.filter { $0.on }.count }

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = paper
        pinHeight(320)
        buildClientBar()
        buildActionRow()
        buildChips()
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
        // Synced client templates plus the merchant's store-info snippets, which ride along as a
        // "Store info" category and insert exactly like any template.
        templates = TemplateStore.load() + StoreInfoStore.asTemplates()
        var seen = Set<String>()
        categories = templates.map { $0.category }.filter { seen.insert($0).inserted }.sorted()
        if let c = selectedCategory, !categories.contains(c) { selectedCategory = nil }
        rebuildClientBar()
        rebuildActionRow()
        rebuildChips()
        rebuildBottomBar()
        let showDraft = (mode == .draft)
        let showTemplateList = (mode == .templates && audience == .client)
        let showGrid = ((mode == .products || mode == .saved) && !products.isEmpty)
        draftView.isHidden = !showDraft
        draftView.text = draftText
        if showDraft && !draftShownAnimated {
            draftShownAnimated = true
            if !UIAccessibility.isReduceMotionEnabled {
                draftView.alpha = 0
                draftView.transform = CGAffineTransform(translationX: 0, y: 10)
                UIView.animate(withDuration: 0.4, delay: 0, options: [.curveEaseOut]) {
                    self.draftView.alpha = 1; self.draftView.transform = .identity
                }
            }
        } else if !showDraft {
            draftShownAnimated = false
            draftView.alpha = 1; draftView.transform = .identity
        }
        grid.isHidden = !showGrid
        table.isHidden = !(mode == .suggestions || (mode == .saved && products.isEmpty) || showTemplateList)

        if mode == .products {
            emptyLabel.text = hasFullAccess
                ? "No products to show. Connect in the Halia app, and note product search needs a Shopify store with published, in-stock items."
                : "Turn on Full Access in Settings to browse and search products."
            emptyLabel.isHidden = !products.isEmpty || busy
        } else if mode == .templates && audience == .team {
            emptyLabel.text = currentRef == nil
                ? "Team mode. Look up a client, then tap Handoff to write a note for a colleague."
                : "Tap Handoff to write a note about them for a colleague."
            emptyLabel.isHidden = false
        } else if mode == .templates && audience == .client && templates.isEmpty {
            emptyLabel.text = "Open the Halia app and tap Connect to sync your templates."
            emptyLabel.isHidden = false
        } else {
            emptyLabel.isHidden = true
        }
        if showGrid { grid.reloadData() }
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
        // The Client / Team toggle is always present, so you can switch audience any time.
        clientBar.addArrangedSubview(audiencePill("Client", active: audience == .client) { [weak self] in self?.setAudience(.client) })
        clientBar.addArrangedSubview(audiencePill("Team", active: audience == .team) { [weak self] in self?.setAudience(.team) })

        if let s = statusText {
            if statusLoading {
                clientBar.addArrangedSubview(PixelLoader())
                let sh = ShimmerLabel()
                sh.text = s
                sh.font = .systemFont(ofSize: 13.5, weight: .medium)
                sh.textColor = .label
                clientBar.addArrangedSubview(sh)
                let el = mutedLabel("0.0s")
                el.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
                el.textColor = .tertiaryLabel
                elapsedLabel = el
                clientBar.addArrangedSubview(el)
            } else {
                clientBar.addArrangedSubview(mutedLabel(s))
            }
            return
        }
        if currentRef == nil {
            clientBar.addArrangedSubview(
                pillButton("＋ Use copied client", filled: true) { [weak self] in self?.useCopiedClient() })
            return
        }
        let label = mutedLabel("For \(clientName ?? currentRef?.value ?? "client")")
        label.textColor = brand
        label.font = .systemFont(ofSize: 14, weight: .semibold)
        clientBar.addArrangedSubview(label)
        clientBar.addArrangedSubview(iconButton("arrow.clockwise") { [weak self] in self?.useCopiedClient() })
        clientBar.addArrangedSubview(iconButton("xmark") { [weak self] in self?.clearClient() })
    }

    private func setAudience(_ a: Audience) {
        guard a != audience else { return }
        audience = a
        mode = .templates; suggestions = []; draftText = ""; pendingCartUrl = nil
        reload()
    }

    private func useCopiedClient() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        guard let ref = ClientClassifier.classify(UIPasteboard.general.string ?? "") else {
            flash("Copy the client's name or number, then tap again"); return
        }
        currentRef = ref
        clientName = ref.kind == .name ? ref.value : nil
        clientCid = nil; cartUrl = nil; cartCount = nil
        mode = .templates; suggestions = []; draftText = ""
        setStatus("Looking up…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.lookup(ref)
                if let n = res.name, !n.isEmpty { clientName = n }
                clientCid = res.cid
                if let u = res.cart?.url, !u.isEmpty { cartUrl = u; cartCount = res.cart?.count }
            } catch { /* keep the copied ref; personalisation still works by name */ }
            setStatus(nil); reload()
        }
    }

    private func clearClient() {
        currentRef = nil; clientName = nil; clientCid = nil; cartUrl = nil; cartCount = nil
        mode = .templates; suggestions = []; draftText = ""; pendingCartUrl = nil
        setStatus(nil); reload()
    }

    // MARK: - Action row (varies by mode)

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

    private func rebuildActionRow() {
        actionStack.arrangedSubviews.forEach { $0.removeFromSuperview() }

        switch mode {
        case .suggestions:
            actionHeight.constant = 46; actionScroll.isHidden = false
            actionStack.addArrangedSubview(pillButton("‹ Templates", filled: false) { [weak self] in self?.backToTemplates() })
            actionStack.addArrangedSubview(pillButton("Send catalogue (\(selectedCount))", filled: true) { [weak self] in self?.sendCatalogue() })
            actionStack.addArrangedSubview(pillButton("Pay in chat (\(selectedCount))", filled: false) { [weak self] in self?.sendCartLink() })

        case .draft:
            actionHeight.constant = 46; actionScroll.isHidden = false
            actionStack.addArrangedSubview(pillButton("‹ Back", filled: false) { [weak self] in self?.backToTemplates() })
            actionStack.addArrangedSubview(pillButton("Insert", filled: true) { [weak self] in self?.insertDraft() })
            for (label, mod) in refinements {
                actionStack.addArrangedSubview(pillButton(label, filled: false) { [weak self] in self?.refine(mod) })
            }

        case .products:
            actionHeight.constant = 46; actionScroll.isHidden = false
            actionStack.addArrangedSubview(pillButton("‹ Back", filled: false) { [weak self] in self?.backToTemplates() })
            actionStack.addArrangedSubview(searchFieldView())

        case .saved:
            actionHeight.constant = 46; actionScroll.isHidden = false
            actionStack.addArrangedSubview(pillButton("‹ Back", filled: false) { [weak self] in self?.backToTemplates() })
            actionStack.addArrangedSubview(pillButton("Build catalogue (\(savedItems.count))", filled: true) { [weak self] in self?.buildCatalogueFromSaved() })
            actionStack.addArrangedSubview(pillButton("💳 Pay in chat", filled: false) { [weak self] in self?.buildCartLinkFromSaved() })
            actionStack.addArrangedSubview(pillButton("Clear", filled: false) { [weak self] in self?.clearSaved() })

        case .templates:
            let base = hasFullAccess && (statusText == nil)
            let clientShow = (currentRef != nil) && base
            let savedN = SavedItemsStore.count
            let show = clientShow || (savedN > 0 && base)
            actionHeight.constant = show ? 46 : 0; actionScroll.isHidden = !show
            guard show else { return }
            // The keyboard is the hub: products saved while browsing (via App Intents) land here.
            if savedN > 0 && hasFullAccess {
                actionStack.addArrangedSubview(pillButton("🛍 Saved (\(savedN))", filled: false) { [weak self] in self?.enterSaved() })
            }
            guard clientShow else { return }

            if audience == .team {
                // Team mode: compose a note ABOUT the client, for a colleague.
                actionStack.addArrangedSubview(pillButton("↗ Handoff", filled: true) { [weak self] in self?.handoff() })
                if clientCid != nil {
                    actionStack.addArrangedSubview(pillButton("Mark contacted", filled: false) { [weak self] in self?.markContacted() })
                }
                return
            }

            // Client mode: compose a message TO the client.
            if cartUrl != nil {
                let n = (cartCount ?? 0) > 0 ? " (\(cartCount!))" : ""
                actionStack.addArrangedSubview(pillButton("🧺 Nudge basket\(n)", filled: true) { [weak self] in self?.nudgeBasket() })
            }
            actionStack.addArrangedSubview(pillButton("✦ Suggest pieces", filled: true) { [weak self] in self?.suggestPieces() })
            actionStack.addArrangedSubview(pillButton("↩ Reply", filled: false) { [weak self] in self?.replyToCopied() })
            if clientCid != nil {
                actionStack.addArrangedSubview(pillButton("Mark contacted", filled: false) { [weak self] in self?.markContacted() })
            }
            let lead = mutedLabel("Draft:")
            lead.font = .systemFont(ofSize: 12, weight: .semibold)
            actionStack.addArrangedSubview(lead)
            for (label, instruction) in intents {
                actionStack.addArrangedSubview(pillButton(label, filled: false) { [weak self] in
                    self?.startDraft(instruction: instruction, thread: nil)
                })
            }
        }
    }

    // MARK: - Team handoff (a note ABOUT the client, for a colleague; never says "hidden VIP")

    private func handoff() {
        guard currentRef != nil else { flash("Look up a client first"); return }
        startDraft(instruction:
            "Write a SHORT internal note for a colleague, not a message to the client. Say who this "
            + "client is, what they want, and the next step, so a teammate can help. Colleague-to-"
            + "colleague tone. Do not use the phrase \"hidden VIP\", and do not mention any grade or score.",
            thread: nil, handoff: true)
    }

    /// Hard guarantee the internal note never carries Halia's internal grade language, whatever the
    /// model returns.
    private func scrubInternal(_ text: String) -> String {
        var out = text
        for phrase in ["hidden vip", "hidden vic"] {
            while let r = out.range(of: phrase, options: .caseInsensitive) {
                out.replaceSubrange(r, with: "VIP")
            }
        }
        return out
    }

    // MARK: - Draft (personal message, previewed before it goes in)

    private func startDraft(instruction: String, thread: [[String: String]]?,
                            cartUrl: String? = nil, handoff: Bool = false) {
        guard let ref = currentRef, !busy else { return }
        pendingCartUrl = cartUrl   // appended to the message only when this draft is inserted
        draftIsHandoff = handoff
        busy = true; setStatus(handoff ? "Writing note…" : "Drafting…", loading: true)
        Task {
            do {
                let res = try await HaliaAPI.current.draft(ref, channel: handoff ? "internal" : "whatsapp",
                                                           instruction: instruction, thread: thread)
                if let n = res.name, !n.isEmpty { clientName = n }
                if let d = res.draft, !d.isEmpty {
                    draftText = handoff ? scrubInternal(d) : d
                    lastThread = thread; mode = .draft; setStatus(nil)
                } else { setStatus("No draft came back") }
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
        let msg = (UIPasteboard.general.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !msg.isEmpty else { flash("Copy the client's message, then tap Reply"); return }
        startDraft(instruction: "Reply warmly and personally to their latest message.",
                   thread: [["from": "them", "text": msg]])
    }

    private func refine(_ modifier: String) {
        guard mode == .draft, !busy, !draftText.isEmpty else { return }
        startDraft(instruction: modifier + " Current draft to adjust: " + draftText,
                   thread: lastThread, cartUrl: pendingCartUrl, handoff: draftIsHandoff)   // keep basket link + handoff scrub across refines
    }

    private func insertDraft() {
        guard !draftText.isEmpty else { return }
        var text = draftText
        if let url = pendingCartUrl, !url.isEmpty { text += "\n\n" + url }   // a basket nudge carries the recovery link
        textDocumentProxy.insertText(text)
        mode = .templates; draftText = ""; lastThread = nil; pendingCartUrl = nil; reload()
    }

    // MARK: - Suggestions

    private func suggestPieces() {
        guard let ref = currentRef, !busy else { return }
        busy = true; setStatus("Finding pieces…", loading: true)
        Task {
            do {
                let picks = try await HaliaAPI.current.suggest(ref, instruction: "")
                suggestions = picks.map { SuggestRow(id: $0.productId, title: $0.title,
                                                     why: $0.why, price: $0.priceText, on: true) }
                if suggestions.isEmpty { setStatus("No suggestions right now") }
                else { mode = .suggestions; setStatus(nil) }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func sendCatalogue() {
        let ids = suggestions.filter { $0.on }.map { $0.id }
        guard !ids.isEmpty else { flash("Pick at least one piece"); return }
        guard !busy else { return }
        busy = true; setStatus("Making a catalogue…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.catalogue(productIds: ids, name: clientName)
                textDocumentProxy.insertText(url)
                mode = .templates; suggestions = []; setStatus(nil)
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func sendCartLink() {
        let ids = suggestions.filter { $0.on }.map { $0.id }
        guard !ids.isEmpty else { flash("Pick at least one piece"); return }
        guard !busy else { return }
        busy = true; setStatus("Making a pay link…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.cartLink(productIds: ids)
                textDocumentProxy.insertText(url)
                mode = .templates; suggestions = []; setStatus(nil)
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    private func backToTemplates() {
        mode = .templates; suggestions = []; products = []; draftText = ""; pendingCartUrl = nil
        searchQuery = ""; searchWork?.cancel(); reload()
    }

    // MARK: - Saved products (the hub) — what App Intents saved while browsing, shown in the keyboard.

    private func enterSaved() {
        savedItems = SavedItemsStore.load()
        products = []; productCartBase = nil
        mode = .saved
        reload()                                       // show the text list at once…
        if !AppGroup.defaults.bool(forKey: "halia.savedHint") {   // one-time discoverability hint
            AppGroup.defaults.set(true, forKey: "halia.savedHint")
            flash("Tap to send · long-press to remove")
        }
        guard hasFullAccess, !savedItems.isEmpty else { return }
        let urls = savedItems.map { $0.url }
        Task {
            do {
                let (prods, base) = try await HaliaAPI.current.productsFromUrls(urls)
                guard mode == .saved else { return }   // …then the image grid takes over
                products = prods; productCartBase = base
                reload()
            } catch { /* keep the text list on a resolve failure */ }
        }
    }

    /// Turn the saved shortlist into one catalogue link and drop it in the chat.
    private func buildCatalogueFromSaved() {
        let urls = savedItems.map { $0.url }
        guard !urls.isEmpty else { flash("Nothing saved yet"); return }
        guard hasFullAccess else { flash("Turn on Full Access to build a catalogue"); return }
        guard !busy else { return }
        busy = true; setStatus("Building a catalogue…", loading: true)
        Task {
            do {
                let r = try await HaliaAPI.current.catalogueFromUrls(urls: urls, name: clientName ?? "")
                if r.url.isEmpty {
                    setStatus("None of your saved items are in this store")
                } else {
                    textDocumentProxy.insertText(r.url)
                    mode = .templates; setStatus(nil); flash("Catalogue inserted ✓")
                }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
    }

    /// Turn the saved shortlist into a Shopify /cart link so the client can pay in the chat.
    private func buildCartLinkFromSaved() {
        let urls = savedItems.map { $0.url }
        guard !urls.isEmpty else { flash("Nothing saved yet"); return }
        guard hasFullAccess else { flash("Turn on Full Access to make a pay link"); return }
        guard !busy else { return }
        busy = true; setStatus("Making a pay link…", loading: true)
        Task {
            do {
                let url = try await HaliaAPI.current.cartLinkFromUrls(urls: urls)
                if url.isEmpty {
                    setStatus("None of your saved items can be bought right now")
                } else {
                    textDocumentProxy.insertText(url)
                    mode = .templates; setStatus(nil); flash("Pay link inserted ✓")
                }
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

    /// A readable name for a saved product: its page title if we have one, else the handle.
    private func savedDisplayName(_ it: SavedItemsStore.Item) -> String {
        if let t = it.title, !t.trimmingCharacters(in: .whitespaces).isEmpty { return t }
        let path = it.url.split(separator: "?").first.map(String.init) ?? it.url
        let tail = path.split(separator: "/").last.map(String.init) ?? it.url
        let name = tail.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
        return name.isEmpty ? it.url : name.capitalized
    }

    // MARK: - Products (a live, searchable image library of the store's catalogue)

    private func enterProducts() {
        mode = .products; products = []; searchQuery = ""; reload()
        runProductSearch("")   // browse the whole catalogue straight away, like a media library
    }

    /// Debounced live search: fired from the in-keyboard keys as the associate types.
    private func afterSearchEdit() {
        rebuildActionRow()      // refresh the search-field display immediately
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
        guard !busy else { return }   // a fetch is in flight; its completion re-runs for the latest text
        busy = true; setStatus(q.isEmpty ? "Loading products…" : "Searching…", loading: true)
        Task {
            do {
                let (items, base) = try await HaliaAPI.current.searchProducts(q)
                products = items; productCartBase = base
                if items.isEmpty { setStatus(q.isEmpty ? nil : "No products for “\(q)”") }
                else { setStatus(nil) }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
            if mode == .products && searchQuery != q { runProductSearch(searchQuery) }   // catch up to newer typing
        }
    }

    // MARK: - Log contacted

    private func markContacted() {
        guard let cid = clientCid else { flash("Look up the client first"); return }
        guard !busy else { return }
        busy = true; setStatus("Logging…", loading: true)
        Task {
            do {
                _ = try await HaliaAPI.current.logContacted(cid: cid, clientName: clientName,
                                                            reason: "Messaged via Halia")
                busy = false; flash("Logged ✓")
            } catch {
                busy = false
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not log")
            }
            reload()
        }
    }

    // MARK: - Category chips

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

    private func rebuildChips() {
        chipsStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let show = (mode == .templates && audience == .client)   // categories are for client templates
        chipsHeight.constant = show ? 44 : 0
        chipsScroll.isHidden = !show
        guard show else { return }
        chipsStack.addArrangedSubview(pillButton("🔍 Products", filled: true) { [weak self] in self?.enterProducts() })
        chipsStack.addArrangedSubview(chip(title: "All", value: nil))
        for c in categories { chipsStack.addArrangedSubview(chip(title: c, value: c)) }
    }

    private func chip(title: String, value: String?) -> UIButton {
        pillButton(title, filled: value == selectedCategory) { [weak self] in
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
            table.topAnchor.constraint(equalTo: chipsScroll.bottomAnchor),
            table.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            table.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
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
        emptyLabel.text = "Open the Halia app and tap Connect to sync your templates."
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
        mode == .suggestions ? suggestions.count : (mode == .saved ? savedItems.count : filtered.count)
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: cellID)
        cell.backgroundColor = .clear
        cell.textLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        cell.detailTextLabel?.textColor = .secondaryLabel
        cell.detailTextLabel?.numberOfLines = 1

        if mode == .suggestions {
            let s = suggestions[indexPath.row]
            cell.textLabel?.text = s.title
            cell.detailTextLabel?.text = [s.price, s.why].compactMap { $0 }.joined(separator: "  ·  ")
            cell.accessoryType = s.on ? .checkmark : .none
        } else if mode == .saved {
            let it = savedItems[indexPath.row]
            cell.textLabel?.text = savedDisplayName(it)
            cell.detailTextLabel?.text = it.url
            cell.accessoryType = .none
        } else {
            let t = filtered[indexPath.row]
            cell.textLabel?.text = t.name
            cell.detailTextLabel?.text = t.preview
            cell.accessoryType = .none
        }
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        if mode == .suggestions {
            suggestions[indexPath.row].on.toggle()
            tableView.reloadRows(at: [indexPath], with: .none)
            rebuildActionRow()
        } else if mode == .saved {
            textDocumentProxy.insertText(savedItems[indexPath.row].url)
            flash("Link inserted ✓")
        } else {
            textDocumentProxy.insertText(filtered[indexPath.row].ready(firstName: currentFirstName))
        }
    }

    /// Swipe-to-remove on the Saved link list (the fallback when a store's images can't be read).
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

    // MARK: - Product grid (collection view)

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
        lp.minimumPressDuration = 0.45                 // long-press a Saved card to remove it
        grid.addGestureRecognizer(lp)
    }

    /// Long-press a card in the Saved grid to prune it from the shortlist (no effect in search mode).
    @objc private func handleGridLongPress(_ g: UILongPressGestureRecognizer) {
        guard g.state == .began, mode == .saved else { return }
        guard let ip = grid.indexPathForItem(at: g.location(in: grid)), ip.item < products.count else { return }
        SavedItemsStore.remove(handle: products[ip.item].handle ?? "")
        products.remove(at: ip.item)
        savedItems = SavedItemsStore.load()
        if products.isEmpty && savedItems.isEmpty { mode = .templates }
        reload()
        flash("Removed ✓")
    }

    func collectionView(_ collectionView: UICollectionView, numberOfItemsInSection section: Int) -> Int {
        products.count
    }

    func collectionView(_ collectionView: UICollectionView, cellForItemAt indexPath: IndexPath) -> UICollectionViewCell {
        let cell = collectionView.dequeueReusableCell(withReuseIdentifier: ProductCell.id, for: indexPath) as! ProductCell
        let p = products[indexPath.item]
        cell.cap.text = p.title
        let token = indexPath.item + 1                     // guards against cell reuse
        cell.img.tag = token
        if let url = p.imageURL { ThumbnailLoader.shared.load(url, into: cell.img, token: token) }
        return cell
    }

    func collectionView(_ collectionView: UICollectionView, didSelectItemAt indexPath: IndexPath) {
        guard indexPath.item < products.count else { return }
        let p = products[indexPath.item]
        // Tapping a product copies its actual image to the clipboard so the associate can paste the
        // photo straight into the chat. A keyboard cannot attach a file itself, so this is the one
        // extra gesture (paste). If there is no image, fall back to sharing the shoppable link.
        guard let url = p.imageURL else { shareProductLink(p); return }
        guard hasFullAccess else { flash("Turn on Full Access to send product images"); return }
        setStatus("Copying image…", loading: true)
        Task {
            do {
                let (data, _) = try await URLSession.shared.data(from: url)
                if let img = UIImage(data: data) {
                    UIPasteboard.general.image = img
                    flash("Image copied. Long-press the chat and tap Paste to send it.")
                } else { shareProductLink(p) }
            } catch { shareProductLink(p) }
        }
    }

    /// Fallback when there is no usable image: drop the shoppable product link in the chat instead.
    private func shareProductLink(_ p: HaliaAPI.Product) {
        if let link = p.shareLink(cartBase: productCartBase), !link.isEmpty {
            textDocumentProxy.insertText(link); flash("Link shared ✓")
        } else {
            flash("Nothing to send for that product")
        }
    }

    func collectionView(_ collectionView: UICollectionView, layout collectionViewLayout: UICollectionViewLayout,
                        sizeForItemAt indexPath: IndexPath) -> CGSize {
        let cols: CGFloat = 3
        let w = floor((collectionView.bounds.width - 24 - 8 * (cols - 1)) / cols)   // 12+12 insets, 8pt gaps
        return CGSize(width: max(60, w), height: max(60, w) + 20)
    }

    // MARK: - Bottom bar (a control row everywhere, a live search keyboard in Products)

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

    /// In Products the bottom bar becomes a full keyboard that types into the search box, so the
    /// catalogue filters live, and the whole keyboard grows taller to fit both keys and results.
    private func rebuildBottomBar() {
        guard bottomBarMode != mode else { return }   // only rebuild on a real mode change
        bottomBarMode = mode
        bottomBar.subviews.forEach { $0.removeFromSuperview() }
        if mode == .products {
            bottomBarHeight.constant = 198
            kbHeight?.constant = 500
            buildSearchKeyboard(into: bottomBar)
        } else {
            bottomBarHeight.constant = 50
            kbHeight?.constant = 320
            buildControlRow(into: bottomBar)
        }
    }

    private func buildControlRow(into bar: UIView) {
        let row = UIStackView()
        row.axis = .horizontal
        row.spacing = 6
        row.translatesAutoresizingMaskIntoConstraints = false
        row.isLayoutMarginsRelativeArrangement = true
        row.layoutMargins = UIEdgeInsets(top: 6, left: 6, bottom: 6, right: 6)
        bar.addSubview(row)

        let globe = key("🌐") { [weak self] in self?.advanceToNextInputMode() }
        let space = key("space") { [weak self] in self?.textDocumentProxy.insertText(" ") }
        let del   = key("⌫")    { [weak self] in self?.textDocumentProxy.deleteBackward() }
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

    // A compact lowercase keyboard whose keys type into the product search, not the chat.
    private func buildSearchKeyboard(into bar: UIView) {
        let col = UIStackView(arrangedSubviews: [
            keyRow("qwertyuiop"),
            keyRow("asdfghjkl"),
            keyRow("zxcvbnm"),
            searchFunctionRow(),
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

    private func keyRow(_ letters: String) -> UIStackView {
        let s = UIStackView()
        s.axis = .horizontal
        s.spacing = 5
        s.distribution = .fillEqually
        for ch in letters {
            let letter = String(ch)
            s.addArrangedSubview(key(letter) { [weak self] in self?.typeSearch(letter) })
        }
        return s
    }

    private func searchFunctionRow() -> UIStackView {
        let s = UIStackView()
        s.axis = .horizontal
        s.spacing = 5
        s.distribution = .fill
        let globe = key("🌐") { [weak self] in self?.advanceToNextInputMode() }
        let space = key("space") { [weak self] in self?.typeSearch(" ") }
        let del   = key("⌫")    { [weak self] in self?.deleteSearch() }
        globe.widthAnchor.constraint(equalToConstant: 58).isActive = true
        del.widthAnchor.constraint(equalToConstant: 58).isActive = true
        [globe, space, del].forEach { s.addArrangedSubview($0) }
        return s
    }

    /// The prominent search box shown at the top of Products; reflects what you type, with a clear ✕.
    private func searchFieldView() -> UIView {
        let box = UIView()
        box.backgroundColor = .systemBackground
        box.layer.cornerRadius = 16
        box.layer.borderWidth = 1
        box.layer.borderColor = brand.withAlphaComponent(0.25).cgColor
        let mag = UILabel(); mag.text = "🔍"; mag.font = .systemFont(ofSize: 13)
        let q = UILabel()
        q.text = searchQuery.isEmpty ? "Search products" : searchQuery
        q.textColor = searchQuery.isEmpty ? .secondaryLabel : .label
        q.font = .systemFont(ofSize: 14, weight: .medium)
        let row = UIStackView(arrangedSubviews: [mag, q])
        row.axis = .horizontal; row.spacing = 6; row.alignment = .center
        row.translatesAutoresizingMaskIntoConstraints = false
        box.addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: box.leadingAnchor, constant: 12),
            row.trailingAnchor.constraint(lessThanOrEqualTo: box.trailingAnchor, constant: -12),
            row.centerYAnchor.constraint(equalTo: box.centerYAnchor),
            box.widthAnchor.constraint(greaterThanOrEqualToConstant: 210),
            box.heightAnchor.constraint(equalToConstant: 34),
        ])
        if !searchQuery.isEmpty {
            let clr = UIButton(type: .system)
            clr.setTitle("✕", for: .normal)
            clr.setTitleColor(.secondaryLabel, for: .normal)
            clr.titleLabel?.font = .systemFont(ofSize: 14, weight: .bold)
            clr.addAction(UIAction { [weak self] _ in self?.clearSearch() }, for: .touchUpInside)
            row.addArrangedSubview(clr)
        }
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
        if statusLoading {
            if loadStart == nil { loadStart = Date() }
            startElapsedTimer()
        } else {
            loadStart = nil
            stopElapsedTimer()
        }
        rebuildClientBar()
        rebuildActionRow()
    }

    private func startElapsedTimer() {
        guard elapsedTimer == nil else { return }
        elapsedTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            guard let self = self, let start = self.loadStart else { return }
            let t = Date().timeIntervalSince(start)
            self.elapsedLabel?.text = t < 60 ? String(format: "%.1fs", t)
                : String(format: "%dm %.0fs", Int(t) / 60, t.truncatingRemainder(dividingBy: 60))
        }
    }
    private func stopElapsedTimer() {
        elapsedTimer?.invalidate(); elapsedTimer = nil
    }

    private func flash(_ s: String) {
        setStatus(s)
        Task {
            try? await Task.sleep(nanoseconds: 1_800_000_000)
            if statusText == s { setStatus(nil) }
        }
    }

    private func mutedLabel(_ text: String) -> UILabel {
        let l = UILabel()
        l.text = text
        l.font = .systemFont(ofSize: 13.5)
        l.textColor = .secondaryLabel
        l.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return l
    }

    private func pillButton(_ title: String, filled: Bool, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        b.setTitle(title, for: .normal)
        b.titleLabel?.font = .systemFont(ofSize: 13, weight: .semibold)
        b.setTitleColor(filled ? .white : brand, for: .normal)
        b.backgroundColor = filled ? brand : tint
        b.layer.cornerRadius = 15
        b.contentEdgeInsets = UIEdgeInsets(top: 7, left: 14, bottom: 7, right: 14)
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return b
    }

    private func audiencePill(_ title: String, active: Bool, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        b.setTitle(title, for: .normal)
        b.titleLabel?.font = .systemFont(ofSize: 12, weight: .semibold)
        b.setTitleColor(active ? .white : brand, for: .normal)
        b.backgroundColor = active ? brand : tint
        b.layer.cornerRadius = 13
        b.contentEdgeInsets = UIEdgeInsets(top: 6, left: 11, bottom: 6, right: 11)
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
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
}
