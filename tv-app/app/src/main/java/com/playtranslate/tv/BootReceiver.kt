package com.playtranslate.tv

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Settings

/** Starts the overlay service when the TV turns on, so the player never has to open the app. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action != Intent.ACTION_BOOT_COMPLETED && action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        // Apps allowed to draw over others may start foreground services from the background.
        if (Prefs(context).autoStart && Settings.canDrawOverlays(context)) {
            runCatching { OverlayService.start(context) }
        }
    }
}
