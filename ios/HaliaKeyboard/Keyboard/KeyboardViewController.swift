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
final class KeyboardViewController: UIInputViewController, UITableViewDataSource, UITableViewDelegate {

    private enum Mode { case templates, suggestions, draft }

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
    private var currentRef: ClientRef?
    private var clientName: String?
    private var clientCid: String?
    private var statusText: String?
    private var busy = false
    private var suggestions: [SuggestRow] = []
    private var draftText = ""
    private var lastThread: [[String: String]]?

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
    private let emptyLabel = UILabel()
    private let cellID = "cell"

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
        buildControls()
        buildDraftView()
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        reload()
    }

    private func pinHeight(_ h: CGFloat) {
        let c = view.heightAnchor.constraint(equalToConstant: h)
        c.priority = UILayoutPriority(999)
        c.isActive = true
    }

    // MARK: - Refresh

    private func reload() {
        templates = TemplateStore.load()
        categories = TemplateStore.categories()
        if let c = selectedCategory, !categories.contains(c) { selectedCategory = nil }
        rebuildClientBar()
        rebuildActionRow()
        rebuildChips()
        let showDraft = (mode == .draft)
        draftView.isHidden = !showDraft
        draftView.text = draftText
        table.isHidden = showDraft
        emptyLabel.isHidden = !(mode == .templates && templates.isEmpty)
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
        if let s = statusText {
            clientBar.addArrangedSubview(mutedLabel(s))
            return
        }
        if currentRef == nil {
            clientBar.addArrangedSubview(
                pillButton("＋  Use copied client", filled: true) { [weak self] in self?.useCopiedClient() })
            return
        }
        let label = mutedLabel("For \(clientName ?? currentRef?.value ?? "client")")
        label.textColor = brand
        label.font = .systemFont(ofSize: 14, weight: .semibold)
        clientBar.addArrangedSubview(label)
        clientBar.addArrangedSubview(iconButton("arrow.clockwise") { [weak self] in self?.useCopiedClient() })
        clientBar.addArrangedSubview(iconButton("xmark") { [weak self] in self?.clearClient() })
    }

    private func useCopiedClient() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        guard let ref = ClientClassifier.classify(UIPasteboard.general.string ?? "") else {
            flash("Copy the client's name or number, then tap again"); return
        }
        currentRef = ref
        clientName = ref.kind == .name ? ref.value : nil
        clientCid = nil; mode = .templates; suggestions = []; draftText = ""
        setStatus("Looking up…")
        Task {
            do {
                let res = try await HaliaAPI.current.lookup(ref)
                if let n = res.name, !n.isEmpty { clientName = n }
                clientCid = res.cid
            } catch { /* keep the copied ref; personalisation still works by name */ }
            setStatus(nil); reload()
        }
    }

    private func clearClient() {
        currentRef = nil; clientName = nil; clientCid = nil
        mode = .templates; suggestions = []; draftText = ""
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

        case .draft:
            actionHeight.constant = 46; actionScroll.isHidden = false
            actionStack.addArrangedSubview(pillButton("‹ Back", filled: false) { [weak self] in self?.backToTemplates() })
            actionStack.addArrangedSubview(pillButton("Insert", filled: true) { [weak self] in self?.insertDraft() })
            for (label, mod) in refinements {
                actionStack.addArrangedSubview(pillButton(label, filled: false) { [weak self] in self?.refine(mod) })
            }

        case .templates:
            let show = (currentRef != nil) && hasFullAccess && (statusText == nil)
            actionHeight.constant = show ? 46 : 0; actionScroll.isHidden = !show
            guard show else { return }
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

    // MARK: - Draft (personal message, previewed before it goes in)

    private func startDraft(instruction: String, thread: [[String: String]]?) {
        guard let ref = currentRef, !busy else { return }
        busy = true; setStatus("Drafting…")
        Task {
            do {
                let res = try await HaliaAPI.current.draft(ref, channel: "whatsapp",
                                                           instruction: instruction, thread: thread)
                if let n = res.name, !n.isEmpty { clientName = n }
                if let d = res.draft, !d.isEmpty {
                    draftText = d; lastThread = thread; mode = .draft; setStatus(nil)
                } else { setStatus("No draft came back") }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false; reload()
        }
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
        startDraft(instruction: modifier + " Keep it in the house voice. Current draft to adjust: " + draftText,
                   thread: lastThread)
    }

    private func insertDraft() {
        guard !draftText.isEmpty else { return }
        textDocumentProxy.insertText(draftText)
        mode = .templates; draftText = ""; lastThread = nil; reload()
    }

    // MARK: - Suggestions

    private func suggestPieces() {
        guard let ref = currentRef, !busy else { return }
        busy = true; setStatus("Finding pieces…")
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
        busy = true; setStatus("Making a catalogue…")
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

    private func backToTemplates() { mode = .templates; suggestions = []; draftText = ""; reload() }

    // MARK: - Log contacted

    private func markContacted() {
        guard let cid = clientCid else { flash("Look up the client first"); return }
        guard !busy else { return }
        busy = true; setStatus("Logging…")
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
        let show = (mode == .templates)
        chipsHeight.constant = show ? 44 : 0
        chipsScroll.isHidden = !show
        guard show else { return }
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
        mode == .suggestions ? suggestions.count : filtered.count
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
        } else {
            textDocumentProxy.insertText(filtered[indexPath.row].ready(firstName: currentFirstName))
        }
    }

    // MARK: - Control row

    private func buildControls() {
        let row = UIStackView()
        row.axis = .horizontal
        row.spacing = 6
        row.translatesAutoresizingMaskIntoConstraints = false
        row.isLayoutMarginsRelativeArrangement = true
        row.layoutMargins = UIEdgeInsets(top: 6, left: 6, bottom: 6, right: 6)
        view.addSubview(row)

        let globe = key("🌐") { [weak self] in self?.advanceToNextInputMode() }
        let space = key("space") { [weak self] in self?.textDocumentProxy.insertText(" ") }
        let del   = key("⌫")    { [weak self] in self?.textDocumentProxy.deleteBackward() }
        let ret   = key("return") { [weak self] in self?.textDocumentProxy.insertText("\n") }
        [globe, del, ret].forEach { $0.widthAnchor.constraint(equalToConstant: 64).isActive = true }
        [globe, space, del, ret].forEach { row.addArrangedSubview($0) }

        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            row.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            row.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
            row.heightAnchor.constraint(equalToConstant: 50),
            table.bottomAnchor.constraint(equalTo: row.topAnchor),
        ])
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

    private func setStatus(_ s: String?) {
        statusText = s
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
