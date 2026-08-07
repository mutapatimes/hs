// Target membership: KEYBOARD EXTENSION ONLY.
//
// The Halia keyboard. It reads templates the host app cached in the App Group and inserts the one
// you tap into whatever field you are in (WhatsApp, Messages, Mail, anywhere). It makes no network
// call, so it needs no Full Access.
//
// Design note: a keyboard extension cannot host editable text fields (there is no keyboard to type
// into them, since this IS the keyboard), so there is no free-text search box. Filtering is done
// with tappable category chips instead, which need no text input.
import UIKit

final class KeyboardViewController: UIInputViewController, UITableViewDataSource, UITableViewDelegate {

    // Halia palette
    private let brand = UIColor(red: 0.12, green: 0.34, blue: 0.29, alpha: 1) // #1F564A
    private let tint  = UIColor(red: 0.90, green: 0.94, blue: 0.92, alpha: 1) // #E6EFEB
    private let paper = UIColor(red: 0.95, green: 0.94, blue: 0.91, alpha: 1) // #F1EFE9

    private var templates: [Template] = []
    private var categories: [String] = []
    private var selectedCategory: String?           // nil == All

    private let chipsScroll = UIScrollView()
    private let chipsStack  = UIStackView()
    private let table       = UITableView(frame: .zero, style: .plain)
    private let emptyLabel  = UILabel()

    private let cellID = "tpl"

    private var filtered: [Template] {
        guard let c = selectedCategory else { return templates }
        return templates.filter { $0.category == c }
    }

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = paper
        pinHeight(300)
        buildChips()
        buildTable()
        buildEmptyLabel()
        buildControls()
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        reload()   // pick up anything the host app synced since we were built
    }

    private func pinHeight(_ h: CGFloat) {
        let c = view.heightAnchor.constraint(equalToConstant: h)
        c.priority = UILayoutPriority(999)     // avoid a hard conflict with the system
        c.isActive = true
    }

    // MARK: - Data

    private func reload() {
        templates = TemplateStore.load()
        categories = TemplateStore.categories()
        if let c = selectedCategory, !categories.contains(c) { selectedCategory = nil }
        rebuildChips()
        emptyLabel.isHidden = !templates.isEmpty
        table.reloadData()
    }

    // MARK: - Chips (category filter)

    private func buildChips() {
        chipsScroll.translatesAutoresizingMaskIntoConstraints = false
        chipsScroll.showsHorizontalScrollIndicator = false
        chipsScroll.backgroundColor = .clear
        view.addSubview(chipsScroll)

        chipsStack.axis = .horizontal
        chipsStack.spacing = 8
        chipsStack.alignment = .center
        chipsStack.translatesAutoresizingMaskIntoConstraints = false
        chipsStack.isLayoutMarginsRelativeArrangement = true
        chipsStack.layoutMargins = UIEdgeInsets(top: 6, left: 10, bottom: 6, right: 10)
        chipsScroll.addSubview(chipsStack)

        NSLayoutConstraint.activate([
            chipsScroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            chipsScroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            chipsScroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            chipsScroll.heightAnchor.constraint(equalToConstant: 46),

            chipsStack.topAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.topAnchor),
            chipsStack.bottomAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.bottomAnchor),
            chipsStack.leadingAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.leadingAnchor),
            chipsStack.trailingAnchor.constraint(equalTo: chipsScroll.contentLayoutGuide.trailingAnchor),
            chipsStack.heightAnchor.constraint(equalTo: chipsScroll.frameLayoutGuide.heightAnchor),
        ])
    }

    private func rebuildChips() {
        chipsStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        chipsStack.addArrangedSubview(makeChip(title: "All", value: nil))
        for c in categories { chipsStack.addArrangedSubview(makeChip(title: c, value: c)) }
    }

    private func makeChip(title: String, value: String?) -> UIButton {
        let b = UIButton(type: .system)
        let selected = (value == selectedCategory)
        b.setTitle(title, for: .normal)
        b.titleLabel?.font = .systemFont(ofSize: 13, weight: .semibold)
        b.setTitleColor(selected ? .white : brand, for: .normal)
        b.backgroundColor = selected ? brand : tint
        b.layer.cornerRadius = 15
        b.contentEdgeInsets = UIEdgeInsets(top: 6, left: 14, bottom: 6, right: 14)
        b.addAction(UIAction { [weak self] _ in
            self?.selectedCategory = value
            self?.rebuildChips()
            self?.table.reloadData()
        }, for: .touchUpInside)
        return b
    }

    // MARK: - Table

    private func buildTable() {
        table.translatesAutoresizingMaskIntoConstraints = false
        table.dataSource = self
        table.delegate = self
        table.backgroundColor = .clear
        table.keyboardDismissMode = .none
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

    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        filtered.count
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        // A fresh subtitle cell each time keeps the two-line layout simple and reliable.
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: cellID)
        let t = filtered[indexPath.row]
        cell.backgroundColor = .clear
        cell.textLabel?.text = t.name
        cell.textLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        cell.detailTextLabel?.text = t.preview
        cell.detailTextLabel?.textColor = .secondaryLabel
        cell.detailTextLabel?.numberOfLines = 1
        cell.accessoryType = .none
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        let t = filtered[indexPath.row]
        textDocumentProxy.insertText(t.readyToInsert)
    }

    // MARK: - Control row (globe / space / delete / return)

    private func buildControls() {
        let row = UIStackView()
        row.axis = .horizontal
        row.distribution = .fill
        row.spacing = 6
        row.translatesAutoresizingMaskIntoConstraints = false
        row.isLayoutMarginsRelativeArrangement = true
        row.layoutMargins = UIEdgeInsets(top: 6, left: 6, bottom: 6, right: 6)
        view.addSubview(row)

        let globe = makeKey("🌐") { [weak self] in self?.advanceToNextInputMode() }
        let space = makeKey("space") { [weak self] in self?.textDocumentProxy.insertText(" ") }
        let del   = makeKey("⌫")    { [weak self] in self?.textDocumentProxy.deleteBackward() }
        let ret   = makeKey("return") { [weak self] in self?.textDocumentProxy.insertText("\n") }

        // space takes the extra width
        space.setContentHuggingPriority(.defaultLow, for: .horizontal)
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

    private func makeKey(_ title: String, action: @escaping () -> Void) -> UIButton {
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
