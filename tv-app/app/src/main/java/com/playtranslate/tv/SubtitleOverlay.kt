package com.playtranslate.tv

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.roundToInt

/**
 * The Arabic subtitle window drawn above everything, including the HDMI input.
 * Must be used from the main thread.
 */
class SubtitleOverlay(private val context: Context) {
    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var view: TextView? = null
    private var params: WindowManager.LayoutParams? = null

    // Style, same keys as the laptop's Style dataclass.
    private var fontSize = 44
    private var textColor = Color.WHITE
    private var speakerColor = Color.parseColor("#FFD54F")
    private var bgColor = Color.BLACK
    private var bgOpacity = 0.55
    private var outline = true
    private var bottomMargin = 0.17
    private var maxWidth = 0.8

    // true while a whole-screen translation (many short lines) is shown: smaller, centred.
    private var pageMode = false

    private val regular: Typeface by lazy { context.resources.getFont(R.font.noto_naskh_arabic) }

    /** Adds the window. Returns false when the overlay permission is missing or refused. */
    fun attach(): Boolean {
        if (view != null) return true
        val tv = TextView(context).apply {
            gravity = Gravity.CENTER
            textDirection = View.TEXT_DIRECTION_RTL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            typeface = regular
            includeFontPadding = true
            visibility = View.GONE
        }
        val type = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            title = "PlayTranslate subtitles"
        }
        return try {
            wm.addView(tv, lp)
            view = tv
            params = lp
            applyStyle()
            true
        } catch (e: Exception) {
            // BadTokenException / SecurityException when the permission is missing.
            false
        }
    }

    fun detach() {
        view?.let { runCatching { wm.removeView(it) } }
        view = null
        params = null
    }

    fun setStyle(style: JSONObject) {
        fontSize = style.optInt("font_size", fontSize)
        textColor = parseColor(style.optString("text_color"), textColor)
        speakerColor = parseColor(style.optString("speaker_color"), speakerColor)
        bgColor = parseColor(style.optString("background_color"), bgColor)
        bgOpacity = style.optDouble("background_opacity", bgOpacity).coerceIn(0.0, 1.0)
        outline = style.optBoolean("outline", outline)
        bottomMargin = style.optDouble("bottom_margin", bottomMargin).coerceIn(0.0, 0.9)
        maxWidth = style.optDouble("max_width", maxWidth).coerceIn(0.3, 1.0)
        applyStyle()
    }

    fun show(lines: JSONArray, page: Boolean = false) {
        val tv = view ?: return
        if (page != pageMode) {
            pageMode = page
            applyStyle()
        }
        val text = SpannableStringBuilder()
        for (i in 0 until lines.length()) {
            val line = lines.optJSONObject(i) ?: continue
            if (text.isNotEmpty()) text.append('\n')
            val speaker = line.optString("speaker", "")
            if (speaker.isNotEmpty()) {
                val start = text.length
                text.append(speaker).append(": ")
                text.setSpan(ForegroundColorSpan(speakerColor), start, text.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                text.setSpan(StyleSpan(Typeface.BOLD), start, text.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
            text.append(line.optString("text", ""))
        }
        tv.text = text
        tv.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
    }

    fun hide() {
        view?.visibility = View.GONE
    }

    private fun applyStyle() {
        val tv = view ?: return
        val lp = params ?: return
        val metrics = context.resources.displayMetrics
        val screenH = minOf(metrics.heightPixels, metrics.widthPixels)
        val screenW = maxOf(metrics.heightPixels, metrics.widthPixels)
        val sizePx = fontSize * screenH / 1080f * (if (pageMode) 0.62f else 1f)
        tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, sizePx)
        tv.setTextColor(textColor)
        tv.maxWidth = (screenW * (if (pageMode) maxOf(maxWidth, 0.9) else maxWidth)).roundToInt()
        val pad = (sizePx * 0.35f).roundToInt()
        tv.setPadding(pad, pad / 2, pad, pad / 2)
        tv.setLineSpacing(0f, 1.15f)
        if (outline) tv.setShadowLayer(sizePx * 0.12f, 0f, 0f, Color.BLACK) else tv.setShadowLayer(0f, 0f, 0f, 0)
        val opacity = if (pageMode) maxOf(bgOpacity, 0.8) else bgOpacity
        val alpha = (opacity * 255).roundToInt().coerceIn(0, 255)
        tv.background = if (alpha == 0) null else GradientDrawable().apply {
            setColor(Color.argb(alpha, Color.red(bgColor), Color.green(bgColor), Color.blue(bgColor)))
            cornerRadius = pad * 0.6f
        }
        if (pageMode) {
            lp.gravity = Gravity.CENTER
            lp.y = 0
        } else {
            lp.gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            lp.y = (screenH * bottomMargin).roundToInt()
        }
        runCatching { wm.updateViewLayout(tv, lp) }
    }

    private fun parseColor(value: String?, fallback: Int): Int =
        if (value.isNullOrEmpty()) fallback else runCatching { Color.parseColor(value) }.getOrDefault(fallback)
}
