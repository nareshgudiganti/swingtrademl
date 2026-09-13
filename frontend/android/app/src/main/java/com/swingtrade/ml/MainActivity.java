package com.swingtrade.ml;

import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // The bundled app loads as https://localhost (androidScheme in
        // capacitor.config.ts), so a plain http:// API call from it is
        // "mixed content" — blocked by WebView's default policy independently
        // of the cleartext/network-security-config settings, which only
        // govern the app's own direct requests, not this. Local dev backend
        // is plain http; production/deployed backend should be https, making
        // this moot outside dev.
        WebView webView = getBridge().getWebView();
        WebSettings settings = webView.getSettings();
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
    }
}
