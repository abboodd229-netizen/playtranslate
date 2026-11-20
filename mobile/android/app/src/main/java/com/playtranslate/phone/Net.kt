package com.playtranslate.phone

import org.java_websocket.WebSocket
import org.java_websocket.handshake.ClientHandshake
import org.java_websocket.server.WebSocketServer
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

object Net {
    const val PORT = 8765           // same as the laptop, so the TV app needs no change
    const val DISCOVERY_PORT = 8766
    const val BEACON_MAGIC = "playtranslate"
    const val PROTOCOL = 1

    /** The phone's Wi-Fi (or hotspot) IPv4 address. */
    fun localIPv4(): String? {
        var fallback: String? = null
        try {
            for (nif in NetworkInterface.getNetworkInterfaces()) {
                if (!nif.isUp || nif.isLoopback) continue
                for (addr in nif.inetAddresses) {
                    if (addr !is Inet4Address || addr.isLoopbackAddress || addr.isLinkLocalAddress) continue
                    val ip = addr.hostAddress ?: continue
                    val name = nif.name
                    if (name.startsWith("wlan")) return ip
                    if (name.startsWith("ap") || name.startsWith("swlan") || name.startsWith("eth")) fallback = fallback ?: ip
                }
            }
        } catch (_: Exception) {
        }
        return fallback
    }
}

/**
 * WebSocket server the TV app connects to, plus the once-a-second UDP beacon that lets
 * the TV find the phone. Speaks protocol v1 exactly like the laptop's server.py.
 */
class DisplayServer(private val name: String, private var style: JSONObject) {
    private val lock = Any()
    private var state: JSONObject? = null
    private var seq = 0
    private var server: WebSocketServer? = null
    private val timers: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor()
    private var beaconSocket: DatagramSocket? = null

    var onClientsChanged: ((Int) -> Unit)? = null
    var onTranslatePage: (() -> Unit)? = null
    var onFailure: ((String) -> Unit)? = null

    val clientCount: Int get() = server?.connections?.size ?: 0

    fun start() {
        val s = object : WebSocketServer(InetSocketAddress(Net.PORT)) {
            override fun onOpen(conn: WebSocket, handshake: ClientHandshake) {
                val hello = JSONObject().put("type", "hello").put("protocol", Net.PROTOCOL)
                    .put("server", name).put("version", "android-${BuildConfig.VERSION_NAME}")
                synchronized(lock) {
                    hello.put("style", style)
                    conn.send(hello.toString())
                    state?.let { conn.send(it.toString()) }
                }
                onClientsChanged?.invoke(connections.size)
            }

            override fun onClose(conn: WebSocket, code: Int, reason: String?, remote: Boolean) {
                onClientsChanged?.invoke(connections.size)
            }

            override fun onMessage(conn: WebSocket, message: String) {
                try {
                    if (JSONObject(message).optString("type") == "translate_page") onTranslatePage?.invoke()
                } catch (_: Exception) {
                }
            }

            override fun onError(conn: WebSocket?, ex: Exception) {
                if (conn == null) onFailure?.invoke("تعذّر فتح المنفذ ${Net.PORT}: ${ex.message}")
            }

            override fun onStart() {}
        }
        s.isReuseAddr = true
        s.connectionLostTimeout = 20
        s.start()
        server = s
        timers.scheduleAtFixedRate({ broadcast(JSONObject().put("type", "ping").put("t", System.currentTimeMillis() / 1000.0)) },
            5, 5, TimeUnit.SECONDS)
        timers.scheduleAtFixedRate({ beacon() }, 0, 1, TimeUnit.SECONDS)
    }

    fun stop() {
        timers.shutdownNow()
        try { server?.stop(500) } catch (_: Exception) {}
        server = null
        beaconSocket?.close()
        beaconSocket = null
    }

    private fun broadcast(msg: JSONObject) {
        try { server?.broadcast(msg.toString()) } catch (_: Exception) {}
    }

    private fun beacon() {
        try {
            val ip = Net.localIPv4() ?: return
            val sock = beaconSocket ?: DatagramSocket().also { it.broadcast = true; beaconSocket = it }
            val payload = JSONObject().put("app", Net.BEACON_MAGIC).put("protocol", Net.PROTOCOL).put("port", Net.PORT)
                .put("name", name).put("ips", JSONArray(listOf(ip))).toString().toByteArray()
            val parts = ip.split(".")
            val targets = linkedSetOf("255.255.255.255")
            if (parts.size == 4) targets.add(parts.take(3).joinToString(".") + ".255")
            for (t in targets) {
                try {
                    sock.send(DatagramPacket(payload, payload.size, InetAddress.getByName(t), Net.DISCOVERY_PORT))
                } catch (_: Exception) {
                }
            }
        } catch (_: Exception) {
        }
    }

    /** lines: [{"speaker": "...", "text": "..."}]; mode "page" = whole-screen translation. */
    fun show(lines: List<Map<String, String>>, mode: String = "subtitle") {
        val msg: JSONObject
        synchronized(lock) {
            seq += 1
            msg = JSONObject().put("type", "show").put("seq", seq)
                .put("lines", JSONArray(lines.map { JSONObject(it) }))
            if (mode == "page") msg.put("mode", "page")
            state = msg
        }
        broadcast(msg)
    }

    fun hide() {
        val msg: JSONObject
        synchronized(lock) {
            state = null
            msg = JSONObject().put("type", "hide").put("seq", seq)
        }
        broadcast(msg)
    }
}
