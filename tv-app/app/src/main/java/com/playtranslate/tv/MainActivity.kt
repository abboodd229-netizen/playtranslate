package com.playtranslate.tv

import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Setup screen, built in code (no XML) and usable with the TV remote's arrows.
 * The real work happens in OverlayService; this screen just grants permission,
 * shows the connection, and offers a test.
 */
class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var prefs: Prefs
    private lateinit var status: TextView
    private lateinit var permissionInfo: TextView
    private lateinit var permissionButton: Button
    private lateinit var autoButton: Button
    private lateinit var hostButton: Button

    private val refresh = object : Runnable {
        override fun run() {
            updateUi()
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL

        val font = resources.getFont(R.font.noto_naskh_arabic)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(48), dp(32), dp(48), dp(32))
            setBackgroundColor(Color.parseColor("#101820"))
            layoutDirection = View.LAYOUT_DIRECTION_RTL
        }
        fun label(text: String, size: Float, color: String = "#ECEFF1") = TextView(this).apply {
            this.text = text
            typeface = font
            setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
            setTextColor(Color.parseColor(color))
            textDirection = View.TEXT_DIRECTION_RTL
            setPadding(0, dp(6), 0, dp(6))
        }
        fun button(text: String, onClick: () -> Unit) = Button(this).apply {
            this.text = text
            typeface = font
            isAllCaps = false
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
            setTextColor(Color.WHITE)
            background = GradientDrawable().apply {
                cornerRadius = dp(8).toFloat()
                setColor(Color.parseColor("#263238"))
                setStroke(dp(2), Color.parseColor("#37474F"))
            }
            setOnFocusChangeListener { v, has ->
                (v.background as GradientDrawable).setStroke(dp(3), Color.parseColor(if (has) "#4FC3F7" else "#37474F"))
            }
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(56)).apply {
                topMargin = dp(10)
            }
        }

        root.addView(label("PlayTranslate", 30f, "#4FC3F7"))
        root.addView(label("ترجمة عربية فوق ألعاب البلايستيشن، من أداة اللابتوب.", 18f, "#B0BEC5"))
        status = label("", 20f)
        root.addView(status)
        permissionInfo = label("", 16f, "#FFB74D")
        root.addView(permissionInfo)
        permissionButton = button("منح صلاحية «العرض فوق التطبيقات»") { requestOverlayPermission() }
        root.addView(permissionButton)
        root.addView(button("عرض نص تجربة لمدة 6 ثوانٍ") {
            OverlayService.start(this, OverlayService.ACTION_TEST)
        })
        hostButton = button("") { askHost() }
        root.addView(hostButton)
        autoButton = button("") {
            prefs.autoStart = !prefs.autoStart
            updateUi()
        }
        root.addView(autoButton)
        root.addView(button("إيقاف الخدمة") { OverlayService.stop(this) })
        root.addView(label(
            "بعد ما يتصل: ارجع لمدخل الـ HDMI حق البلايستيشن والعب. الترجمة تطلع فوق اللعبة تلقائيًا.",
            16f, "#90A4AE"
        ))

        setContentView(ScrollView(this).apply { addView(root) })
        permissionButton.requestFocus()
    }

    override fun onResume() {
        super.onResume()
        if (Settings.canDrawOverlays(this)) {
            OverlayService.start(this)
        }
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    private fun updateUi() {
        val canDraw = Settings.canDrawOverlays(this)
        status.text = if (canDraw) ServiceState.describe() else "الخطوة الأولى: امنح صلاحية العرض فوق التطبيقات."
        permissionButton.visibility = if (canDraw) View.GONE else View.VISIBLE
        permissionInfo.visibility = if (canDraw) View.GONE else View.VISIBLE
        permissionInfo.text = "إذا ما فتحت صفحة الصلاحية في تلفزيونك، شغّل من الكمبيوتر:\n" +
            "adb shell appops set $packageName SYSTEM_ALERT_WINDOW allow"
        val manual = prefs.manualHost
        hostButton.text = if (manual.isEmpty()) "عنوان اللابتوب: تلقائي (اضغط للكتابة يدويًا)"
        else "عنوان اللابتوب: $manual (اضغط للتغيير)"
        autoButton.text = if (prefs.autoStart) "التشغيل مع التلفزيون: مفعّل ✓" else "التشغيل مع التلفزيون: متوقف"
    }

    private fun requestOverlayPermission() {
        val intents = listOf(
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")),
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION),
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")),
        )
        for (intent in intents) {
            try {
                startActivity(intent)
                return
            } catch (_: ActivityNotFoundException) {
            } catch (_: SecurityException) {
            }
        }
        AlertDialog.Builder(this)
            .setTitle("صفحة الصلاحية غير موجودة")
            .setMessage(
                "بعض التلفزيونات تخفي هذه الصفحة. جرّب: الإعدادات ← التطبيقات ← وصول خاص للتطبيقات ← " +
                    "العرض فوق التطبيقات الأخرى.\n\nأو من كمبيوتر على نفس الشبكة:\n" +
                    "adb connect <عنوان التلفزيون>\nadb shell appops set $packageName SYSTEM_ALERT_WINDOW allow"
            )
            .setPositiveButton("حسنًا", null)
            .show()
    }

    private fun askHost() {
        val input = EditText(this).apply {
            setText(prefs.manualHost)
            hint = "192.168.1.20"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            gravity = Gravity.LEFT
            textDirection = View.TEXT_DIRECTION_LTR
        }
        AlertDialog.Builder(this)
            .setTitle("عنوان اللابتوب")
            .setMessage("تجده في أداة اللابتوب، تبويب التشغيل. اتركه فارغًا للبحث التلقائي.")
            .setView(input)
            .setPositiveButton("حفظ") { _, _ ->
                prefs.manualHost = input.text.toString()
                OverlayService.start(this, OverlayService.ACTION_RECONNECT)
                updateUi()
            }
            .setNegativeButton("إلغاء", null)
            .show()
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()
}
