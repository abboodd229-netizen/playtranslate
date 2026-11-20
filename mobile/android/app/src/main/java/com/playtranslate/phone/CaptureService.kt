package com.playtranslate.phone

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.PowerManager
import android.util.DisplayMetrics
import android.view.WindowManager

/**
 * Foreground service that receives the phone's screen (Android's screen-share permission)
 * while PS Remote Play is open, and feeds frames to the [Reader]. Keeps running while
 * the player is in the Remote Play app.
 */
class CaptureService : Service() {
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var server: DisplayServer? = null
    private var textReader: Reader? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var width = 0
    private var height = 0
    private var dpi = 0
    @Volatile private var busy = false
    private var lastRun = 0L
    private var scratch: Bitmap? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (projection != null) return START_NOT_STICKY
        val resultCode = intent?.getIntExtra(EXTRA_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data: Intent? = if (Build.VERSION.SDK_INT >= 33) intent?.getParcelableExtra(EXTRA_DATA, Intent::class.java)
        else @Suppress("DEPRECATION") intent?.getParcelableExtra(EXTRA_DATA)
        // Android 14+: the service must be in the foreground before it takes the projection.
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFY_ID, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIFY_ID, notification())
        }
        if (resultCode != Activity.RESULT_OK || data == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val p = mpm.getMediaProjection(resultCode, data)
        if (p == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        projection = p
        start(p)
        return START_NOT_STICKY
    }

    private fun start(p: MediaProjection) {
        val settings = Settings.load(this)
        val srv = DisplayServer("PlayTranslate (Android)", settings.tvStyle())
        srv.onClientsChanged = { Status.tvCount = it }
        srv.onFailure = { msg -> Status.lastError = msg }
        srv.start()
        server = srv
        val r = Reader(this, settings, srv, TranslationCache(Reader.cacheFile(this)))
        srv.onTranslatePage = { r.requestPage() }
        textReader = r

        val t = HandlerThread("pt-capture").also { it.start() }
        thread = t
        handler = Handler(t.looper)
        p.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopSelf() }
        }, handler)

        measure()
        val ir = newReader()
        reader = ir
        display = p.createVirtualDisplay("PlayTranslate", width, height, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, ir.surface, null, handler)

        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PlayTranslate:capture").also { it.acquire(6 * 60 * 60 * 1000L) }
        Status.running = true
        Status.lastError = ""
    }

    /** Screen size, scaled so the longer side is at most 1920 px (enough for subtitles, lighter to read). */
    private fun measure() {
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION") wm.defaultDisplay.getRealMetrics(metrics)
        val scale = minOf(1f, 1920f / maxOf(metrics.widthPixels, metrics.heightPixels))
        width = (metrics.widthPixels * scale).toInt().coerceAtLeast(2)
        height = (metrics.heightPixels * scale).toInt().coerceAtLeast(2)
        dpi = metrics.densityDpi
    }

    private fun newReader(): ImageReader {
        val ir = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        ir.setOnImageAvailableListener({ onFrame(it) }, handler)
        return ir
    }

    /** Remote Play turns the phone sideways: follow the new screen size. */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        val h = handler ?: return
        h.post {
            val oldW = width
            val oldH = height
            measure()
            if (width == oldW && height == oldH) return@post
            val old = reader
            val ir = newReader()
            reader = ir
            display?.resize(width, height, dpi)
            display?.surface = ir.surface
            old?.close()
            scratch = null
        }
    }

    private fun onFrame(ir: ImageReader) {
        val image = try { ir.acquireLatestImage() } catch (_: Exception) { null } ?: return
        try {
            val now = System.currentTimeMillis()
            if (busy || now - lastRun < 300) return
            val plane = image.planes[0]
            val pixelStride = plane.pixelStride
            val rowPadding = plane.rowStride - pixelStride * image.width
            val fullWidth = image.width + rowPadding / pixelStride
            var bmp = scratch
            if (bmp == null || bmp.width != fullWidth || bmp.height != image.height) {
                bmp = Bitmap.createBitmap(fullWidth, image.height, Bitmap.Config.ARGB_8888)
                scratch = bmp
            }
            bmp!!.copyPixelsFromBuffer(plane.buffer)
            val frame = if (fullWidth != image.width) Bitmap.createBitmap(bmp, 0, 0, image.width, image.height) else bmp
            busy = true
            lastRun = now
            Thread {
                try {
                    textReader?.process(frame)
                } catch (_: Exception) {
                } finally {
                    if (frame !== bmp) frame.recycle()
                    busy = false
                }
            }.start()
        } finally {
            image.close()
        }
    }

    override fun onDestroy() {
        Status.running = false
        Status.tvCount = 0
        try { server?.hide() } catch (_: Exception) {}
        display?.release()
        reader?.close()
        projection?.stop()
        projection = null
        textReader?.cache?.save()
        textReader?.close()
        server?.stop()
        thread?.quitSafely()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun notification(): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "الترجمة", NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, CaptureService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        return b.setContentTitle("PlayTranslate يترجم")
            .setContentText("افتح PS Remote Play. الترجمة تطلع على التلفزيون.")
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "إيقاف", stop).build())
            .setOngoing(true)
            .build()
    }

    companion object {
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val ACTION_STOP = "stop"
        private const val CHANNEL = "capture"
        private const val NOTIFY_ID = 1
    }
}
