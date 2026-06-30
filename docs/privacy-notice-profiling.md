# Privacy-notice wording: the logic of the profiling (template)

> **Template only. Review with a solicitor before use.** This is suggested wording for a
> Merchant to adapt into its own customer-facing privacy notice. It is not legal advice. The
> Merchant is the Controller and is responsible for the accuracy and completeness of its own
> notice.

UK GDPR Articles 13 and 14 require a Controller that profiles its customers to tell them, in
plain language, that profiling happens and the **logic involved**. The paragraph below is
written for the Merchant to paste (and adapt) into the "How we use your data" section of its
privacy notice. It describes Halia honestly while keeping the language accessible.

---

## Suggested customer-facing wording

> **Understanding our customers.** To give our best customers a more personal level of service,
> we use a tool that reviews information we already hold about you, such as your order history
> and the area you have your orders delivered to, and estimates how likely you are to be a
> high-value client. This helps a member of our team decide who to reach out to personally, for
> example with an early look at a collection or an invitation to an event.
>
> **What it looks at.** The estimate is based on **commercial and address facts**: how much and
> how often you have bought from us, and publicly recognisable signs of an area or a
> professional email domain. It does **not** use your nationality, your ethnicity, your name, or
> the origin of your name.
>
> **A person always decides.** The tool only highlights customers for our team to consider. It
> does not make any automatic decision about you, it never withholds a product, price, or
> service from you, and a member of our team always decides whether to get in touch. The effect,
> at most, is that you may hear from us a little more personally.
>
> **Why we are allowed to do this.** We rely on our legitimate interest in understanding our
> customers and offering a relevant, personal service, balanced against your rights. You can
> object to this profiling at any time by contacting us at [contact], and we will stop including
> you.

---

## Notes for the Merchant (do not publish this section)

- **Signal categories, plainly.** Halia scores on: spend and order history; address and postcode
  matched to recognised prime areas; and work / professional email or company tells. These are
  **wealth and address facts**.
- **Explicitly excluded by default.** Nationality, billing country as an origin proxy, dialling-
  code, name structure, name origin, and heritage-surname signals are **off by default** and are
  not used unless you have documented a lawful basis and asked us to enable them. Keep them off
  unless your solicitor has signed off a specific lawful basis.
- **Basis.** The wording above assumes **legitimate interests**. You must complete a Legitimate
  Interests Assessment (see `docs/dpia-lia-support.md`) and keep it on file. If you instead rely
  on consent, change the "Why we are allowed to do this" paragraph accordingly.
- **Right to object.** Give a working contact route and make sure your team can act on an
  objection (exclude that customer from outreach lists).
- **No significant effect.** Keep the "a person always decides" and "never withholds" statements
  true in practice. They are what keep this outside Article 22 (decisions based solely on
  automated processing with legal or similarly significant effect). If you ever wire a score
  directly to a price, an offer gate, or a refusal, this wording no longer holds and you must
  reassess.
- **Children.** If a material share of your customers are under 18, take additional advice: the
  Children's Code expects a higher bar and profiling of children for these purposes may not be
  appropriate.
