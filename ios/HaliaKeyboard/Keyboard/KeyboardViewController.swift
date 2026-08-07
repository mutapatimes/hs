// Target membership: KEYBOARD EXTENSION ONLY.
//
// The Halia composer. It helps an associate send a personal, on-voice message to a VIP without
// leaving WhatsApp. There is no grade here on purpose: the point is the message, not a letter.
//
// Two layers of usefulness:
//   1. Offline, no Full Access needed: your synced templates, inserted with one tap (the house
//      catalogue rides along via the {catalog_link} template).
//   2. With Full Access on: copy the client's name or number in the chat, tap "Use copied client",
//      and the keyboard looks them up. Then templates fill with their real name, and the intent
//      chips draft a personal message for them in your house voice.
//
// It never reads the WhatsApp screen. The client is identified only by what you copy.
import UIKit

@MainActor
final class KeyboardViewController: UIInputViewController, UITableViewDataSource, UITableViewDelegate {

    // Halia palette
    private let brand = UIColor(red: 0.12, green: 0.34, blue: 0.29, alpha: 1) // #1F564A
    private let tint  = UIColor(red: 0.90, green: 0.94, blue: 0.92, alpha: 1) // #E6EFEB
    private let paper = UIColor(red: 0.95, green: 0.94, blue: 0.91, alpha: 1) // #F1EFE9

    // Intent chips: (short label, the instruction sent to /v1/extension/draft)
    private let intents: [(String, String)] = [
        ("Hello", "Send a warm, personal hello to reconnect."),
        ("Private preview", "Invite them to a private preview before it opens to everyone."),
        ("New arrival", "Tell them about a new arrival they would love, based on what they buy."),
        ("Follow up", "Follow up warmly on their recent visit or order."),
        ("Thank you", "Thank them personally for a recent purchase."),
        ("Win-back", "A gentle, warm message to reconnect after a quiet spell."),
    ]

    // State
    private var currentRef: ClientRef?
    private var clientName: String?      // resolved display name from lookup
    private var statusText: String?      // transient ("Looking up…", an error), shown in the client bar
    private var busy = false

    private var templates: [Template] = []
    private var categories: [String] = []
    private var selectedCategory: String?

    // Views
    private let clientBar = UIStackView()
    private let intentsScroll = UIScrollView()
    private let intentsStack = UIStackView()
    private var intentsHeight: NSLayoutConstraint!
    private let chipsScroll = UIScrollView()
    private let chipsStack = UIStackView()
    private let table = UITableView(frame: .zero, style: .plain)
    private let emptyLabel = UILabel()
    private let cellID = "tpl"

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

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = paper
        pinHeight(320)
        buildClientBar()
        buildIntents()
        buildChips()
        buildTable()
        buildEmptyLabel()
        buildControls()
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

    // MARK: - Data

    private func reload() {
        templates = TemplateStore.load()
        categories = TemplateStore.categories()
        if let c = selectedCategory, !categories.contains(c) { selectedCategory = nil }
        rebuildClientBar()
        rebuildIntents()
        rebuildChips()
        emptyLabel.isHidden = !templates.isEmpty
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
            let b = pillButton("＋  Use copied client", filled: true) { [weak self] in self?.useCopiedClient() }
            clientBar.addArrangedSubview(b)
            return
        }
        let name = clientName ?? currentRef?.value ?? "client"
        let label = mutedLabel("For \(name)")
        label.textColor = brand
        label.font = .systemFont(ofSize: 14, weight: .semibold)
        clientBar.addArrangedSubview(label)
        clientBar.addArrangedSubview(iconButton("arrow.clockwise") { [weak self] in self?.useCopiedClient() })
        clientBar.addArrangedSubview(iconButton("xmark") { [weak self] in self?.clearClient() })
    }

    private func useCopiedClient() {
        guard hasFullAccess else { flash("Turn on Full Access in Settings"); return }
        let raw = UIPasteboard.general.string ?? ""
        guard let ref = ClientClassifier.classify(raw) else {
            flash("Copy the client's name or number, then tap again"); return
        }
        currentRef = ref
        clientName = ref.kind == .name ? ref.value : nil
        setStatus("Looking up…")
        Task {
            do {
                let res = try await HaliaAPI.current.lookup(ref)
                if let n = res.name, !n.isEmpty { clientName = n }
            } catch {
                // Keep the client set from what was copied; personalisation still works by name.
            }
            setStatus(nil)
            reload()
        }
    }

    private func clearClient() {
        currentRef = nil
        clientName = nil
        setStatus(nil)
        reload()
    }

    // MARK: - Intents (draft a personal message)

    private func buildIntents() {
        intentsScroll.translatesAutoresizingMaskIntoConstraints = false
        intentsScroll.showsHorizontalScrollIndicator = false
        view.addSubview(intentsScroll)
        intentsStack.axis = .horizontal
        intentsStack.spacing = 8
        intentsStack.alignment = .center
        intentsStack.translatesAutoresizingMaskIntoConstraints = false
        intentsStack.isLayoutMarginsRelativeArrangement = true
        intentsStack.layoutMargins = UIEdgeInsets(top: 5, left: 12, bottom: 5, right: 12)
        intentsScroll.addSubview(intentsStack)

        intentsHeight = intentsScroll.heightAnchor.constraint(equalToConstant: 0)
        NSLayoutConstraint.activate([
            intentsScroll.topAnchor.constraint(equalTo: clientBar.bottomAnchor),
            intentsScroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            intentsScroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            intentsHeight,
            intentsStack.topAnchor.constraint(equalTo: intentsScroll.contentLayoutGuide.topAnchor),
            intentsStack.bottomAnchor.constraint(equalTo: intentsScroll.contentLayoutGuide.bottomAnchor),
            intentsStack.leadingAnchor.constraint(equalTo: intentsScroll.contentLayoutGuide.leadingAnchor),
            intentsStack.trailingAnchor.constraint(equalTo: intentsScroll.contentLayoutGuide.trailingAnchor),
            intentsStack.heightAnchor.constraint(equalTo: intentsScroll.frameLayoutGuide.heightAnchor),
        ])
    }

    private func rebuildIntents() {
        intentsStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let show = (currentRef != nil) && hasFullAccess && (statusText == nil)
        intentsHeight.constant = show ? 44 : 0
        intentsScroll.isHidden = !show
        guard show else { return }
        let lead = mutedLabel("Draft:")
        lead.font = .systemFont(ofSize: 12, weight: .semibold)
        intentsStack.addArrangedSubview(lead)
        for (label, instruction) in intents {
            intentsStack.addArrangedSubview(
                pillButton(label, filled: false) { [weak self] in self?.draftIntent(instruction) })
        }
    }

    private func draftIntent(_ instruction: String) {
        guard let ref = currentRef, !busy else { return }
        busy = true
        setStatus("Drafting…")
        Task {
            do {
                let res = try await HaliaAPI.current.draft(ref, channel: "whatsapp", instruction: instruction)
                if let n = res.name, !n.isEmpty { clientName = n }
                if let d = res.draft, !d.isEmpty {
                    textDocumentProxy.insertText(d)
                    setStatus(nil)
                } else {
                    setStatus("No draft came back")
                }
            } catch {
                setStatus((error as? LocalizedError)?.errorDescription ?? "Could not reach Halia")
            }
            busy = false
            reload()
        }
    }

    // MARK: - Category chips

    private func buildChips() {
        chipsScroll.translatesAutoresizingMaskIntoConstraints = false
        chipsScroll.showsHorizontalScrollIndicator = false
        view.addSubview(chipsScroll)
        chipsStack.axis = .horizontal
        chipsStack.spacing = 8
        chipsStack.alignment = .center
        chipsStack.translatesAutoresizingMaskIntoConstraints = false
        chipsStack.isLayoutMarginsRelativeArrangement = true
        chipsStack.layoutMargins = UIEdgeInsets(top: 5, left: 12, bottom: 5, right: 12)
        chipsScroll.addSubview(chipsStack)
        NSLayoutConstraint.activate([
            chipsScroll.topAnchor.constraint(equalTo: intentsScroll.bottomAnchor),
            chipsScroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            chipsScroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            chipsScroll.heightAnchor.constraint(equalToConstant: 44),
            chipsStack.topAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.topAnchor),
            chipsStack.bottomAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.bottomAnchor),
            chipsStack.leadingAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.leadingAnchor),
            chipsStack.trailingAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.trailingAnchor),
            chipsStack.heightAnchor.constraint(equalTo: chipsScroll.frameLayoutGuide.heightAnchor),
        ])
    }

    private func rebuildChips() {
        chipsStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        chipsStack.addArrangedSubview(chip(title: "All", value: nil))
        for c in categories { chipsStack.addArrangedSubview(chip(title: c, value: c)) }
    }

    private func chip(title: String, value: String?) -> UIButton {
        let selected = (value == selectedCategory)
        return pillButton(title, filled: selected) { [weak self] in
            self?.selectedCategory = value
            self?.rebuildChips()
            self?.table.reloadData()
        }
    }

    // MARK: - Templates table

    private func buildTable() {
        table.translatesAutoresizingMaskIntoConstraints = false
        table.dataSource = self
        table.delegate = self
        table.backgroundColor = .clear
        table.register(UITableViewCell.self, forCellReuseIdentifier: cellID)
        view.addSubview(table)
        NSLayoutConstraint.activate([
            table.topAnchor.constraint(equalTo: chipsScroll.bottomAnchor),
            table.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            table.trailingAnchor.constraint(equalTo: view.trailingAnchor),
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

    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int { filtered.count }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: cellID)
        let t = filtered[indexPath.row]
        cell.backgroundColor = .clear
        cell.textLabel?.text = t.name
        cell.textLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        cell.detailTextLabel?.text = t.preview
        cell.detailTextLabel?.textColor = .secondaryLabel
        cell.detailTextLabel?.numberOfLines = 1
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        let t = filtered[indexPath.row]
        textDocumentProxy.insertText(t.ready(firstName: currentFirstName))
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

    // MARK: - Small view helpers

    private func setStatus(_ s: String?) {
        statusText = s
        rebuildClientBar()
        rebuildIntents()
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
