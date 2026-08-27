<?php
/**
 * The connect flow and the Halia admin page.
 *
 * Connect mints a read/write REST key inside this site (the same table WooCommerce uses for
 * its own keys), posts it once to Halia with the store address, and keeps only what Halia
 * returns: the tenant key, the sign-in link and the order-webhook address. Client data never
 * passes through the plugin; Halia reads the store directly with that key.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Halia_Connect {

    const OPTION = 'halia_connection';

    public static function init() {
        add_action( 'admin_menu', [ __CLASS__, 'menu' ] );
        add_action( 'admin_post_halia_connect', [ __CLASS__, 'handle_connect' ] );
        add_action( 'admin_post_halia_disconnect', [ __CLASS__, 'handle_disconnect' ] );
        add_filter( 'plugin_action_links_' . plugin_basename( HALIA_FILE ), [ __CLASS__, 'action_links' ] );
    }

    public static function connection() {
        $c = get_option( self::OPTION );
        return is_array( $c ) ? $c : [];
    }

    public static function connected() {
        $c = self::connection();
        return ! empty( $c['shop'] );
    }

    public static function menu() {
        add_menu_page( 'Halia', 'Halia', 'manage_woocommerce', 'halia', [ __CLASS__, 'page' ], 'dashicons-star-filled', 56 );
    }

    public static function action_links( $links ) {
        array_unshift( $links, '<a href="' . esc_url( admin_url( 'admin.php?page=halia' ) ) . '">Open</a>' );
        return $links;
    }

    public static function page() {
        if ( ! current_user_can( 'manage_woocommerce' ) ) {
            return;
        }
        $c      = self::connection();
        $notice = isset( $_GET['halia_error'] ) ? sanitize_text_field( wp_unslash( $_GET['halia_error'] ) ) : '';
        ?>
        <div class="wrap" style="max-width:720px">
            <h1 style="font-weight:500">Halia</h1>
            <?php if ( $notice ) : ?>
                <div class="notice notice-error"><p><?php echo esc_html( $notice ); ?></p></div>
            <?php endif; ?>
            <?php if ( self::connected() ) : ?>
                <p>Connected as <strong><?php echo esc_html( $c['label'] ); ?></strong>. Halia scores your client book from your own orders and keeps none of it.</p>
                <p>
                    <a class="button button-primary" target="_blank" rel="noopener" href="<?php echo esc_url( $c['dashboard'] ); ?>">Open Halia</a>
                    <?php if ( ! empty( $c['open_url'] ) ) : ?>
                        <span style="margin-left:8px;color:#646970">A sign-in link was also emailed to you.</span>
                    <?php endif; ?>
                </p>
                <h2 style="font-weight:500;margin-top:32px">Order updates</h2>
                <p>Every new or updated order is sent to Halia so scores stay current. Webhook: <code><?php echo esc_html( Halia_Webhooks::status() ); ?></code></p>
                <h2 style="font-weight:500;margin-top:32px">Basket links</h2>
                <p>Associates can send a client a link that fills their basket and opens checkout. This plugin handles those links at <code>/?halia-cart=…</code>. In a page or post, <code>[halia_basket items="12:1,15:2" label="Add these to my basket"]</code> renders the same link.</p>
                <?php if ( ! empty( $c['capture_url'] ) ) : ?>
                <h2 style="font-weight:500;margin-top:32px">Client capture</h2>
                <p>Clients can leave their details at the till or online. The page is in your store's name; Halia never appears on it.</p>
                <p><a target="_blank" rel="noopener" href="<?php echo esc_url( $c['capture_url'] ); ?>"><?php echo esc_html( $c['capture_url'] ); ?></a></p>
                <?php if ( ! empty( $c['capture_qr'] ) ) : ?>
                    <p><img src="<?php echo esc_attr( $c['capture_qr'] ); ?>" alt="Client capture QR" width="180" height="180" style="border:1px solid #dcdcde;padding:8px;background:#fff"></p>
                    <p><button class="button" onclick="var w=window.open('','_blank','width=480,height=640');w.document.write('<title>Leave your details</title><div style=\'font-family:Georgia,serif;text-align:center;padding:40px\'><h1 style=\'font-weight:400\'><?php echo esc_js( $c['label'] ); ?></h1><p>Leave your details and we will look after you.</p><img width=260 src=\'<?php echo esc_js( $c['capture_qr'] ); ?>\'></div>');w.document.close();w.print();">Print a till card</button></p>
                <?php endif; ?>
                <p>In a page or post, <code>[halia_capture label="Join our client book"]</code> renders a button to the capture page.</p>
                <?php endif; ?>
                <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" style="margin-top:40px">
                    <?php wp_nonce_field( 'halia_disconnect' ); ?>
                    <input type="hidden" name="action" value="halia_disconnect">
                    <button class="button" onclick="return confirm('Disconnect this store from Halia? The REST key and webhooks will be removed.')">Disconnect</button>
                </form>
            <?php else : ?>
                <p>Halia reads your orders and customers through the WooCommerce API and grades every client by capacity to spend. Connecting creates a read/write API key for Halia and starts the first scoring run. Nothing changes in your store.</p>
                <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                    <?php wp_nonce_field( 'halia_connect' ); ?>
                    <input type="hidden" name="action" value="halia_connect">
                    <p>
                        <label for="halia_email">Your email (for the sign-in link)</label><br>
                        <input type="email" id="halia_email" name="email" class="regular-text" value="<?php echo esc_attr( wp_get_current_user()->user_email ); ?>">
                    </p>
                    <p><button class="button button-primary">Connect to Halia</button></p>
                </form>
            <?php endif; ?>
        </div>
        <?php
    }

    /** Mint a WooCommerce REST key for Halia, the same way WooCommerce's own key screen does. */
    private static function create_key( $user_id ) {
        global $wpdb;
        $consumer_key    = 'ck_' . wc_rand_hash();
        $consumer_secret = 'cs_' . wc_rand_hash();
        $wpdb->insert(
            $wpdb->prefix . 'woocommerce_api_keys',
            [
                'user_id'         => $user_id,
                'description'     => 'Halia',
                'permissions'     => 'read_write',
                'consumer_key'    => wc_api_hash( $consumer_key ),
                'consumer_secret' => $consumer_secret,
                'truncated_key'   => substr( $consumer_key, -7 ),
            ],
            [ '%d', '%s', '%s', '%s', '%s', '%s' ]
        );
        return [ 'id' => $wpdb->insert_id, 'ck' => $consumer_key, 'cs' => $consumer_secret ];
    }

    private static function delete_key( $key_id ) {
        global $wpdb;
        if ( $key_id ) {
            $wpdb->delete( $wpdb->prefix . 'woocommerce_api_keys', [ 'key_id' => (int) $key_id ], [ '%d' ] );
        }
    }

    public static function handle_connect() {
        if ( ! current_user_can( 'manage_woocommerce' ) ) {
            wp_die( 'Not allowed' );
        }
        check_admin_referer( 'halia_connect' );
        $email = isset( $_POST['email'] ) ? sanitize_email( wp_unslash( $_POST['email'] ) ) : '';
        $key   = self::create_key( get_current_user_id() );

        $resp = wp_remote_post( HALIA_APP_URL . '/connect/woocommerce/plugin', [
            'timeout' => 30,
            'headers' => [ 'Content-Type' => 'application/json' ],
            'body'    => wp_json_encode( [
                'store_url'       => home_url( '/' ),
                'consumer_key'    => $key['ck'],
                'consumer_secret' => $key['cs'],
                'site_name'       => get_bloginfo( 'name' ),
                'email'           => $email,
                'plugin_version'  => HALIA_VERSION,
            ] ),
        ] );

        $body = is_wp_error( $resp ) ? null : json_decode( wp_remote_retrieve_body( $resp ), true );
        if ( is_wp_error( $resp ) || wp_remote_retrieve_response_code( $resp ) !== 200 || empty( $body['shop'] ) ) {
            self::delete_key( $key['id'] );
            $why = is_wp_error( $resp ) ? $resp->get_error_message() : ( $body['detail'] ?? 'Halia did not accept the connection.' );
            wp_safe_redirect( admin_url( 'admin.php?page=halia&halia_error=' . rawurlencode( $why ) ) );
            exit;
        }

        update_option( self::OPTION, [
            'shop'         => $body['shop'],
            'label'        => $body['label'] ?? get_bloginfo( 'name' ),
            'dashboard'    => $body['dashboard'] ?? HALIA_APP_URL . '/app',
            'open_url'     => $body['open_url'] ?? '',
            'webhook_url'  => $body['webhook_url'] ?? '',
            'capture_url'  => $body['capture_url'] ?? '',
            'capture_qr'   => $body['capture_qr'] ?? '',
            'key_id'       => $key['id'],
            'connected_at' => time(),
        ], false );
        Halia_Webhooks::ensure( true );

        // The private sign-in link is used once, in a new tab, and not kept around.
        if ( ! empty( $body['open_url'] ) && empty( $body['reconnected'] ) ) {
            wp_redirect( $body['open_url'] );  // phpcs:ignore WordPress.Security.SafeRedirect
            exit;
        }
        wp_safe_redirect( admin_url( 'admin.php?page=halia' ) );
        exit;
    }

    public static function handle_disconnect() {
        if ( ! current_user_can( 'manage_woocommerce' ) ) {
            wp_die( 'Not allowed' );
        }
        check_admin_referer( 'halia_disconnect' );
        $c = self::connection();
        Halia_Webhooks::remove();
        self::delete_key( $c['key_id'] ?? 0 );
        delete_option( self::OPTION );
        wp_safe_redirect( admin_url( 'admin.php?page=halia' ) );
        exit;
    }
}
