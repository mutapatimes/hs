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
        <style>
            .halia-wrap{max-width:880px;margin:24px 20px 0 0;color:#1a1a1d;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
            .halia-wrap h1{font-family:"Cormorant Garamond",Georgia,serif;font-weight:500;font-size:34px;letter-spacing:.01em;margin:0 0 4px;color:#1a1a1d}
            .halia-wrap .halia-lede{color:#5b5b60;font-size:14px;margin:0 0 22px}
            .halia-head{display:flex;justify-content:space-between;align-items:center;gap:16px;background:#fff;border:1px solid #E4E2DB;border-radius:10px;padding:20px 24px;margin-bottom:16px}
            .halia-head strong{font-weight:600}
            .halia-status{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:#5b5b60}
            .halia-status i{width:8px;height:8px;border-radius:50%;background:#7fae9d;display:inline-block}
            .halia-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
            @media (max-width:900px){.halia-grid{grid-template-columns:1fr}}
            .halia-card{background:#fff;border:1px solid #E4E2DB;border-radius:10px;padding:20px 24px}
            .halia-card.wide{grid-column:1/-1}
            .halia-card h2{font-family:"Cormorant Garamond",Georgia,serif;font-weight:500;font-size:22px;margin:0 0 8px;color:#1a1a1d}
            .halia-card p{margin:0 0 10px;font-size:14px;line-height:1.55;color:#3a3a3f}
            .halia-card p:last-child{margin-bottom:0}
            .halia-card code{background:#f6f6f4;border:1px solid #E4E2DB;border-radius:4px;padding:2px 6px;font-size:12.5px;color:#1a1a1d}
            .halia-btn{display:inline-block;background:#1a1a1d;color:#fff !important;border:1px solid #1a1a1d;border-radius:6px;padding:9px 16px;font-size:14px;text-decoration:none;cursor:pointer;line-height:1.2}
            .halia-btn:hover{background:#2e2e33}
            .halia-btn.ghost{background:#fff;color:#1a1a1d !important;border-color:#c9c7bf}
            .halia-btn.ghost:hover{background:#f6f6f4}
            .halia-capture{display:flex;gap:24px;align-items:flex-start}
            .halia-capture img{width:168px;height:168px;border:1px solid #E4E2DB;border-radius:8px;padding:8px;background:#fff;flex:none}
            .halia-capture a.lnk{color:#1a1a1d;word-break:break-all}
            .halia-foot{margin-top:24px;font-size:13px;color:#8a8a90}
            .halia-foot button{background:none;border:0;padding:0;color:#8a8a90;text-decoration:underline;cursor:pointer;font-size:13px}
            .halia-foot button:hover{color:#1a1a1d}
            .halia-field{margin:14px 0 18px}
            .halia-field label{display:block;font-size:13px;color:#5b5b60;margin-bottom:6px}
            .halia-field input{width:100%;max-width:380px;border:1px solid #c9c7bf;border-radius:6px;padding:8px 10px;font-size:14px}
            .halia-err{background:#fff;border:1px solid #E4E2DB;border-radius:10px;padding:14px 18px;margin-bottom:16px;color:#8a2f2f;font-size:14px}
        </style>
        <div class="wrap halia-wrap">
            <h1>Halia</h1>
            <p class="halia-lede">Private client intelligence for luxury retail.</p>
            <?php if ( $notice ) : ?>
                <div class="halia-err"><?php echo esc_html( $notice ); ?></div>
            <?php endif; ?>
            <?php if ( self::connected() ) : ?>
                <div class="halia-head">
                    <div>
                        <div><strong><?php echo esc_html( $c['label'] ); ?></strong></div>
                        <div class="halia-status"><i></i>Connected. Halia scores your client book from your own orders and keeps none of it.</div>
                    </div>
                    <a class="halia-btn" target="_blank" rel="noopener" href="<?php echo esc_url( $c['dashboard'] ); ?>">Open Halia</a>
                </div>
                <div class="halia-grid">
                    <div class="halia-card">
                        <h2>Order updates</h2>
                        <p>Every new or updated order reaches Halia as it happens, so scores stay current.</p>
                        <p><code><?php echo esc_html( Halia_Webhooks::status() ); ?></code></p>
                    </div>
                    <div class="halia-card">
                        <h2>Basket links</h2>
                        <p>Associates send a client a link that fills their basket and opens checkout. In a page or post:</p>
                        <p><code>[halia_basket items="12:1,15:2" label="Add these to my basket"]</code></p>
                    </div>
                    <?php if ( ! empty( $c['capture_url'] ) ) : ?>
                    <div class="halia-card wide">
                        <h2>Client capture</h2>
                        <div class="halia-capture">
                            <?php if ( ! empty( $c['capture_qr'] ) ) : ?>
                                <img src="<?php echo esc_attr( $c['capture_qr'] ); ?>" alt="Client capture QR">
                            <?php endif; ?>
                            <div>
                                <p>Clients leave their details at the till or online. The page carries your store's name; Halia never appears on it.</p>
                                <p><a class="lnk" target="_blank" rel="noopener" href="<?php echo esc_url( $c['capture_url'] ); ?>"><?php echo esc_html( $c['capture_url'] ); ?></a></p>
                                <p>In a page or post: <code>[halia_capture label="Join our client book"]</code></p>
                                <?php if ( ! empty( $c['capture_qr'] ) ) : ?>
                                <p><button type="button" class="halia-btn ghost" onclick="var w=window.open('','_blank','width=480,height=640');w.document.write('<title>Leave your details</title><div style=\'font-family:Georgia,serif;text-align:center;padding:40px\'><h1 style=\'font-weight:400\'><?php echo esc_js( $c['label'] ); ?></h1><p>Leave your details and we will look after you.</p><img width=260 src=\'<?php echo esc_js( $c['capture_qr'] ); ?>\'></div>');w.document.close();w.print();">Print a till card</button></p>
                                <?php endif; ?>
                            </div>
                        </div>
                    </div>
                    <?php endif; ?>
                </div>
                <form class="halia-foot" method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                    <?php wp_nonce_field( 'halia_disconnect' ); ?>
                    <input type="hidden" name="action" value="halia_disconnect">
                    Connected <?php echo esc_html( date_i18n( get_option( 'date_format' ), (int) ( $c['connected_at'] ?? time() ) ) ); ?>.
                    <button type="submit" onclick="return confirm('Disconnect this store from Halia? The API key and webhooks will be removed.')">Disconnect</button>
                </form>
            <?php else : ?>
                <div class="halia-card">
                    <h2>Connect your store</h2>
                    <p>Halia reads your orders and customers through the WooCommerce API and grades every client by capacity to spend. Connecting creates an API key for Halia and starts the first scoring run. Nothing changes in your store.</p>
                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'halia_connect' ); ?>
                        <input type="hidden" name="action" value="halia_connect">
                        <div class="halia-field">
                            <label for="halia_email">Your email, for the sign-in link</label>
                            <input type="email" id="halia_email" name="email" value="<?php echo esc_attr( wp_get_current_user()->user_email ); ?>">
                        </div>
                        <button type="submit" class="halia-btn">Connect to Halia</button>
                    </form>
                </div>
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
