/**
 * POS modal — the discreet play for the customer on the cart.
 * See the NOTE in Tile.jsx about the 2026 POS web-component API and reconciliation.
 * Re-fetches from the backend (stateless) so it always agrees with the dashboard.
 */
import '@shopify/ui-extensions/point-of-sale';
import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { scoreCustomer, currentCustomerId } from './api';

function money(v) {
  return v != null ? `£${Math.round(v).toLocaleString('en-GB')}` : '—';
}

function Modal() {
  const [s, setS] = useState({ loading: true });

  useEffect(() => {
    (async () => {
      try {
        setS({ loading: false, ...(await scoreCustomer(currentCustomerId())) });
      } catch (e) {
        setS({ loading: false, error: 'Could not reach Halia.' });
      }
    })();
  }, []);

  if (s.loading) {
    return (<s-screen name="Halia" title="Halia"><s-text>Checking…</s-text></s-screen>);
  }
  if (s.error) {
    return (<s-screen name="Halia" title="Halia"><s-banner variant="critical">{s.error}</s-banner></s-screen>);
  }
  if (!s.matched) {
    return (
      <s-screen name="Halia" title="Halia">
        <s-text>No history for this client yet — a genuine walk-in until they buy.</s-text>
      </s-screen>
    );
  }

  return (
    <s-screen name="Halia" title={`Halia · ${s.grade}`}>
      <s-stack direction="block" gap="400">
        <s-stack direction="inline" gap="200">
          <s-badge tone={s.vic ? 'success' : 'neutral'}>{s.grade}</s-badge>
          {s.vic ? <s-badge tone="attention">Potential VIC</s-badge> : null}
        </s-stack>
        {s.gesture ? (
          <s-section title="The discreet play"><s-text>{s.gesture}</s-text></s-section>
        ) : null}
        {s.signals && s.signals.length ? (
          <s-section title="Why"><s-text>{s.signals.join(' · ')}</s-text></s-section>
        ) : null}
        <s-section title="On file">
          <s-text>Spend to date: {money(s.spend)}{s.score != null ? ` · score ${s.score}` : ''}</s-text>
        </s-section>
      </s-stack>
    </s-screen>
  );
}

export default async () => {
  render(<Modal />, document.body);
};
