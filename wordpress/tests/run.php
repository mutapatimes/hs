<?php
/**
 * Stub-WordPress smoke test for the plugin's pure logic. Run: php wordpress/tests/run.php
 * Stubs only the WP/WC functions the tested paths touch; anything else missing is a real finding.
 */
define( 'ABSPATH', __DIR__ . '/' );
define( 'HALIA_APP_URL', 'https://halia.test' );
define( 'HOUR_IN_SECONDS', 3600 );
define( 'DAY_IN_SECONDS', 86400 );

$GLOBALS['options'] = [];
function get_option( $k, $d = false ) { return $GLOBALS['options'][ $k ] ?? $d; }
function update_option( $k, $v, $a = true ) { $GLOBALS['options'][ $k ] = $v; return true; }
function delete_option( $k ) { unset( $GLOBALS['options'][ $k ] ); }
function home_url( $p = '' ) { return 'https://maison.example' . $p; }
function add_query_arg( $k, $v, $u ) { return $u . ( strpos( $u, '?' ) === false ? '?' : '&' ) . $k . '=' . rawurlencode( $v ); }
function esc_url( $u ) { return htmlspecialchars( $u, ENT_QUOTES ); }
function esc_attr( $s ) { return htmlspecialchars( $s, ENT_QUOTES ); }
function esc_html( $s ) { return htmlspecialchars( $s, ENT_QUOTES ); }
function shortcode_atts( $d, $a, $s = '' ) { return array_merge( $d, array_intersect_key( (array) $a, $d ) ); }
function add_action() {} function add_filter() {} function add_shortcode() {} function register_rest_route() {}
function plugin_basename( $f ) { return basename( dirname( $f ) ) . '/' . basename( $f ); }
function get_transient( $k ) { return $GLOBALS['options'][ 't_' . $k ] ?? false; }
function set_transient( $k, $v, $e = 0 ) { $GLOBALS['options'][ 't_' . $k ] = $v; }

require __DIR__ . '/../halia/includes/class-halia-connect.php';
require __DIR__ . '/../halia/includes/class-halia-cart.php';
require __DIR__ . '/../halia/includes/class-halia-webhooks.php';
require __DIR__ . '/../halia/includes/class-halia-pages.php';

$fail = 0;
function check( $name, $ok ) { global $fail; echo ( $ok ? 'ok   ' : 'FAIL ' ) . $name . "\n"; if ( ! $ok ) { $fail++; } }

// basket shortcode: only digits, colons and commas survive; renders a checkout-filling link
$html = Halia_Cart::basket_shortcode( [ 'items' => '12:1,15:2<script>', 'label' => 'Add these' ] );
check( 'basket link carries the items', strpos( $html, 'halia-cart=12%3A1%2C15%3A2' ) !== false );
check( 'basket link strips junk', strpos( $html, 'script' ) === false );
check( 'basket link empty without items', Halia_Cart::basket_shortcode( [] ) === '' );

// capture shortcode: nothing before connection, a link after
check( 'capture empty before connect', Halia_Cart::capture_shortcode( [] ) === '' );
update_option( 'halia_connection', [ 'shop' => 'maison-example', 'capture_url' => 'https://halia.test/c/abc' ] );
check( 'capture link after connect', strpos( Halia_Cart::capture_shortcode( [ 'label' => 'Join' ] ), 'https://halia.test/c/abc' ) !== false );
check( 'connected() reads the option', Halia_Connect::connected() );

// webhook ensure is a no-op without WooCommerce classes and never throws
Halia_Webhooks::ensure( true );
check( 'webhooks ensure tolerates no WooCommerce', true );

// client pages: only invite and capture paths are ever fetched
check( 'pages accept invite', Halia_Pages::valid( 'i/abc.DEF-1' ) );
check( 'pages accept invite ics', Halia_Pages::valid( 'i/abc.ics' ) );
check( 'pages accept capture check', Halia_Pages::valid( 'c/x4PtofO230wfxiuc/check' ) );
check( 'pages reject traversal', ! Halia_Pages::valid( '../wp-config.php' ) && ! Halia_Pages::valid( 'i/../x' ) );
check( 'pages reject other paths', ! Halia_Pages::valid( 'app' ) && ! Halia_Pages::valid( 'v1/seats' ) );

exit( $fail ? 1 : 0 );
