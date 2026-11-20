package com.playtranslate.tv

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

/**
 * Runs in the background while the TV shows the game:
 *  1. finds the laptop (UDP beacon, or the address typed in the app),
 *  2. keeps a WebSocket open to it,
 *  3. draws each subtitle it receives over the screen.
 */
class OverlayService : Service() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var prefs: Prefs
    private lateinit var overlay: SubtitleOverlay
    private val http = OkHttpClient.Builder()
        .pingInterval(10, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    @Volatile private var socket: WebSocket? = null
    @Volatile private var connecting = false
    @Volatile private var stopped = false
    @Volatile private var discoveredHost: String = ""
    private var discoveryThread: Thread? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private var retryDelayMs = 1000L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        overlay = SubtitleOverlay(this)
        startInForeground()
        ServiceState.running = true
        ServiceState.overlayOk = Settings.canDrawOverlays(this) && overlay.attach()
        acquireMulticastLock()
        startDiscovery()
        connectSoon(0)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TEST -> showTest()
            ACTION_RECONNECT -> {
                socket?.close(1000, "reconnect")
                socket = null
                retryDelayMs = 1000L
                connectSoon(0)
            }
        }
        if (!ServiceState.overlayOk && Settings.canDrawOverlays(this)) {
            ServiceState.overlayOk = overlay.attach()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopped = true
        ServiceState.running = false
        ServiceState.connectedTo = ""
        socket?.close(1000, "bye")
        discoveryThread?.interrupt()
        multicastLock?.let { if (it.isHeld) it.release() }
        main.removeCallbacksAndMessages(null)
        overlay.detach()
        http.dispatcher.executorService.shutdown()
        super.onDestroy()
    }

    // ---------------------------------------------------------------- foreground

    private fun startInForeground() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "PlayTranslate", NotificationManager.IMPORTANCE_LOW)
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("PlayTranslate")
            .setContentText("يعرض الترجمة فوق اللعبة")
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    // ---------------------------------------------------------------- discovery

    private fun acquireMulticastLock() {
        // Without this some Wi-Fi chips drop broadcast packets to save power.
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
        multicastLock = wifi.createMulticastLock("playtranslate").apply {
            setReferenceCounted(false)
            runCatching { acquire() }
        }
    }

    private fun startDiscovery() {
        discoveryThread = Thread({
            var sock: DatagramSocket? = null
            while (!stopped) {
                try {
                    val s = sock ?: DatagramSocket(null).apply {
                        reuseAddress = true
                        broadcast = true
                        soTimeout = 3000
                        bind(InetSocketAddress(Prefs.DISCOVERY_PORT))
                    }.also { sock = it }
                    val buf = ByteArray(2048)
                    val packet = DatagramPacket(buf, buf.size)
                    s.receive(packet)
                    val msg = JSONObject(String(packet.data, 0, packet.length, Charsets.UTF_8))
                    if (msg.optString("app") != "playtranslate") continue
                    val host = packet.address.hostAddress ?: continue
                    val port = msg.optInt("port", Prefs.DEFAULT_PORT)
                    val found = "$host:$port"
                    if (found != discoveredHost) {
                        discoveredHost = found
                        ServiceState.serverName = msg.optString("name", "")
                    }
                    if (socket == null && !connecting && prefs.manualHost.isEmpty()) connectSoon(0)
                } catch (_: SocketTimeoutException) {
                    // keep listening
                } catch (_: InterruptedException) {
                    break
                } catch (e: Exception) {
                    // Port busy or network change: rebuild the socket after a pause.
                    runCatching { sock?.close() }
                    sock = null
                    try { Thread.sleep(2000) } catch (_: InterruptedException) { break }
                }
            }
            runCatching { sock?.close() }
        }, "discovery").apply { isDaemon = true; start() }
    }

    private fun targetHost(): String {
        val manual = prefs.manualHost
        val raw = when {
            manual.isNotEmpty() -> manual
            discoveredHost.isNotEmpty() -> discoveredHost
            else -> prefs.lastHost
        }
        if (raw.isEmpty()) return ""
        return if (raw.contains(':')) raw else "$raw:${Prefs.DEFAULT_PORT}"
    }

    // ---------------------------------------------------------------- websocket

    private fun connectSoon(delayMs: Long) {
        main.postDelayed({ connect() }, delayMs)
    }

    private fun connect() {
        if (stopped || socket != null || connecting) return
        val host = targetHost()
        if (host.isEmpty()) {
            ServiceState.lastError = ""
            connectSoon(2000)
            return
        }
        connecting = true
        val request = Request.Builder().url("ws://$host/ws").build()
        http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                socket = webSocket
                connecting = false
                retryDelayMs = 1000L
                prefs.lastHost = host
                ServiceState.connectedTo = host
                ServiceState.lastError = ""
                val hello = JSONObject()
                    .put("type", "hello").put("client", "tv").put("protocol", 1)
                    .put("name", Build.MODEL ?: "TV")
                webSocket.send(hello.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
                when (msg.optString("type")) {
                    "hello" -> {
                        ServiceState.serverName = msg.optString("server", ServiceState.serverName)
                        msg.optJSONObject("style")?.let { s -> main.post { overlay.setStyle(s) } }
                    }
                    "style" -> msg.optJSONObject("style")?.let { s -> main.post { overlay.setStyle(s) } }
                    "show" -> {
                        val lines = msg.optJSONArray("lines") ?: JSONArray()
                        ServiceState.linesShown++
                        val page = msg.optString("mode") == "page"
                        main.post { overlay.show(lines, page) }
                    }
                    "hide" -> main.post { overlay.hide() }
                    "ping" -> webSocket.send(JSONObject().put("type", "pong").put("t", msg.opt("t")).toString())
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = lost(webSocket, "")

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
                lost(webSocket, t.message ?: t.javaClass.simpleName)
        })
    }

    private fun lost(ws: WebSocket, error: String) {
        if (socket === ws || socket == null) socket = null
        connecting = false
        ServiceState.connectedTo = ""
        ServiceState.lastError = error
        main.post { overlay.hide() }
        if (!stopped) {
            connectSoon(retryDelayMs)
            retryDelayMs = (retryDelayMs * 2).coerceAtMost(8000L)
        }
    }

    // ---------------------------------------------------------------- test

    private fun showTest() {
        if (!ServiceState.overlayOk) return
        val lines = JSONArray().put(
            JSONObject().put("speaker", "PlayTranslate").put("text", "هذا نص تجربة. إذا شفته فوق صورة اللعبة فكل شيء جاهز.")
        )
        overlay.show(lines)
        main.postDelayed({ overlay.hide() }, 6000)
    }

    companion object {
        const val ACTION_TEST = "com.playtranslate.tv.TEST"
        const val ACTION_RECONNECT = "com.playtranslate.tv.RECONNECT"
        private const val CHANNEL = "overlay"
        private const val NOTIFICATION_ID = 1

        fun start(context: Context, action: String? = null) {
            val intent = Intent(context, OverlayService::class.java)
            if (action != null) intent.action = action
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, OverlayService::class.java))
        }
    }
}
