<?php
/**
 * Basket links and live baskets. The features the standalone helper file offered, now part of
 * the plugin: /?halia-cart=PRODUCT:QTY[:VARIATION],… fills the basket and opens checkout, and
 * GET /wp-json/wc-halia/v1/carts lists live logged-in baskets for the dashboard (authenticated
 * by the same REST key as wc/v3).
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Halia_Cart {

    public static function init() {
        add_action( 'wp_loaded', [ __CLASS__, 'handle_cart_link' ], 20 );
        add_action( 'rest_api_init', [ __CLASS__, 'routes' ] );
        add_shortcode( 'halia_basket', [ __CLASS__, 'basket_shortcode' ] );
        add_shortcode( 'halia_capture', [ __CLASS__, 'capture_shortcode' ] );
    }

    /** [halia_basket items="12:1,15:2" label="Add these to my basket"] */
    public static function basket_shortcode( $atts ) {
        $a = shortcode_atts( [ 'items' => '', 'label' => 'Add to my basket', 'class' => 'button' ], $atts, 'halia_basket' );
        $items = preg_replace( '/[^0-9:,]/', '', (string) $a['items'] );
        if ( ! $items ) {
            return '';
        }
        $url = add_query_arg( 'halia-cart', $items, home_url( '/' ) );
        return '<a class="' . esc_attr( $a['class'] ) . '" href="' . esc_url( $url ) . '">' . esc_html( $a['label'] ) . '</a>';
    }

    /** [halia_capture label="Join our client book"] */
    public static function capture_shortcode( $atts ) {
        $a = shortcode_atts( [ 'label' => 'Join our client book', 'class' => 'button' ], $atts, 'halia_capture' );
        $c = Halia_Connect::connection();
        if ( empty( $c['capture_url'] ) ) {
            return '';
        }
        return '<a class="' . esc_attr( $a['class'] ) . '" href="' . esc_url( $c['capture_url'] ) . '" rel="noopener">' . esc_html( $a['label'] ) . '</a>';
    }

    public static function handle_cart_link() {
        if ( empty( $_GET['halia-cart'] ) || ! function_exists( 'WC' ) || ! WC()->cart ) {
            return;
        }
        $added = 0;
        foreach ( explode( ',', sanitize_text_field( wp_unslash( $_GET['halia-cart'] ) ) ) as $item ) {
            $bits = array_map( 'absint', explode( ':', $item ) );
            $pid  = $bits[0] ?? 0;
            $qty  = max( 1, $bits[1] ?? 1 );
            $vid  = $bits[2] ?? 0;
            if ( $pid && WC()->cart->add_to_cart( $pid, $qty, $vid ) ) {
                $added++;
            }
        }
        if ( $added ) {
            wp_safe_redirect( wc_get_checkout_url() );
            exit;
        }
    }

    public static function routes() {
        register_rest_route( 'wc-halia/v1', '/carts', [
            'methods'             => 'GET',
            'permission_callback' => function () {
                return current_user_can( 'manage_woocommerce' );
            },
            'callback'            => [ __CLASS__, 'carts' ],
        ] );
    }

    public static function carts() {
        global $wpdb;
        $rows = $wpdb->get_results(
            "SELECT session_key, session_value, session_expiry FROM {$wpdb->prefix}woocommerce_sessions
             WHERE session_expiry > UNIX_TIMESTAMP() ORDER BY session_expiry DESC LIMIT 500",
            ARRAY_A
        );
        $out = [];
        foreach ( (array) $rows as $r ) {
            if ( ! ctype_digit( (string) $r['session_key'] ) ) {
                continue; // logged-in customers only
            }
            $sess = maybe_unserialize( $r['session_value'] );
            $cart = isset( $sess['cart'] ) ? maybe_unserialize( $sess['cart'] ) : [];
            if ( empty( $cart ) || ! is_array( $cart ) ) {
                continue;
            }
            $count = 0;
            $value = 0.0;
            $items = [];
            foreach ( $cart as $line ) {
                $q      = (int) ( $line['quantity'] ?? 0 );
                $count += $q;
                $value += (float) ( $line['line_total'] ?? 0 );
                $p      = wc_get_product( ! empty( $line['variation_id'] ) ? $line['variation_id'] : $line['product_id'] );
                $items[] = [ 'title' => $p ? $p->get_name() : 'Item', 'qty' => $q ];
            }
            if ( $count < 1 ) {
                continue;
            }
            $user  = get_userdata( (int) $r['session_key'] );
            $out[] = [
                'customer_id' => (int) $r['session_key'],
                'email'       => $user ? $user->user_email : '',
                'value'       => round( $value, 2 ),
                'count'       => $count,
                'items'       => $items,
                'updated'     => gmdate( 'Y-m-d', (int) $r['session_expiry'] - 2 * DAY_IN_SECONDS ),
                'url'         => wc_get_cart_url(),
            ];
        }
        return rest_ensure_response( $out );
    }
}
