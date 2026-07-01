/**
 * POS home Smart Grid tile — lights up when the cart's customer is a potential VIC.
 *
 * NOTE: this targets the 2026 POS UI extension API (Preact + web components,
 * `@shopify/ui-extensions/point-of-sale`). Component tag/prop specifics can shift
 * between POS API versions and CANNOT be validated inside this repo. If
 * `shopify app dev` scaffolds a different entry signature or component set, keep the
 * LOGIC here (subscribe to the cart → scoreCustomer → decide the label) and reconcile
 * the render/JSX with the generated boilerplate. The backend contract in ./api.js is
 * the stable part.
 */
import '@shopify/ui-extensions/point-of-sale';
import { render } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { scoreCustomer } from './api';

function Tile() {
  const [tile, setTile] = useState({ title: 'Halia', subtitle: 'No customer on cart', enabled: false });

  useEffect(() => {
    const cart = shopify.cart.current;
    async function evaluate(state) {
      const id = state && state.customer ? state.customer.id : null;
      if (!id) return setTile({ title: 'Halia', subtitle: 'No customer on cart', enabled: false });
      setTile((t) => ({ ...t, subtitle: 'Checking…' }));
      try {
        const r = await scoreCustomer(id);
        if (!r.matched) return setTile({ title: 'Halia', subtitle: 'No history yet', enabled: false });
        setTile({
          title: r.vic ? `${r.grade} · Potential VIC` : `Halia · ${r.grade}`,
          subtitle: r.vic ? 'Tap for the discreet play' : 'No strong VIC signal',
          enabled: !!r.vic,
        });
      } catch (e) {
        setTile({ title: 'Halia', subtitle: 'Lookup unavailable', enabled: false });
      }
    }
    evaluate(cart.value);
    const unsubscribe = cart.subscribe(evaluate);
    return () => unsubscribe && unsubscribe();
  }, []);

  return (
    <s-tile
      title={tile.title}
      subtitle={tile.subtitle}
      enabled={tile.enabled}
      onpress={() => shopify.action.presentModal()}
    />
  );
}

export default async () => {
  render(<Tile />, document.body);
};
