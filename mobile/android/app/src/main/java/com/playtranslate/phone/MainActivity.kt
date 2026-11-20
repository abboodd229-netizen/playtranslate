package com.playtranslate.phone

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView

/** The one screen: settings, TV test, start/stop. Plain views, Arabic, right-to-left. */
class MainActivity : Activity() {
    private lateinit var settings: Settings
    private val main = Handler(Looper.getMainLooper())
    private lateinit var statusView: TextView
    private lateinit var lastView: TextView
    private lateinit var startButton: Button
    private lateinit var testButton: Button
    private lateinit var testView: TextView
    private lateinit var ipView: TextView
    private lateinit var keyMessage: TextView
    private lateinit var regionBox: LinearLayout
    private lateinit var cacheView: TextView
    private var tester: DisplayServer? = null
    private var testStop: Runnable? = null

    private val accent = Color.parseColor("#FFC94D")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = Settings.load(this)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(40))
            layoutDirection = View.LAYOUT_DIRECTION_RTL
        }
        val scroll = ScrollView(this).apply { addView(root); setBackgroundColor(Color.parseColor("#101318")) }
        setContentView(scroll)

        root.addView(text("PlayTranslate", 26f, bold = true, color = accent))
        root.addView(text("ترجمة حوارات ألعاب البلايستيشن للعربي على التلفزيون، من جوالك.", 14f, color = Color.parseColor("#A6ADBB")))

        // Status
        statusView = text("", 17f, bold = true)
        lastView = text("", 14f, color = Color.parseColor("#C9CED8"))
        root.addView(card(statusView, lastView))

        // Start
        startButton = button("") { toggleCapture() }.apply {
            background = rounded(accent, 14f)
            setTextColor(Color.parseColor("#14161B"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 19f)
        }
        root.addView(startButton, LinearLayout.LayoutParams(-1, dp(60)).apply { topMargin = dp(14) })
        root.addView(text("بعد الضغط وافق على \"مشاركة الشاشة\" (اختر الشاشة كاملة إذا سألك)، وبعدها افتح PS Remote Play وشغّل اللعبة. الترجمة تطلع على التلفزيون.", 13f, color = Color.parseColor("#8C94A4")))

        // DeepL key
        root.addView(header("مفتاح الترجمة (DeepL)"))
        val keyEdit = EditText(this).apply {
            hint = "الصق مفتاح DeepL هنا"
            setText(settings.deeplKey)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            textDirection = View.TEXT_DIRECTION_LTR
            setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
            addTextChangedListener(watcher { settings.deeplKey = it; save() })
        }
        keyMessage = text("", 13f, color = Color.parseColor("#C9CED8"))
        root.addView(card(keyEdit, button("فحص المفتاح") { checkKey() }, keyMessage,
            text("نفس المفتاح المجاني حق اللابتوب يشتغل هنا. الجمل المكررة تنحفظ في الجوال وما تنحسب.", 12f, color = Color.parseColor("#8C94A4"))))

        // TV
        root.addView(header("التلفزيون"))
        testButton = button("اختبار التلفزيون") { toggleTest() }
        testView = text("", 14f)
        ipView = text("", 14f, color = Color.parseColor("#C9CED8"))
        root.addView(card(testButton, testView, ipView,
            text("الجوال والتلفزيون على نفس الواي فاي. تطبيق التلفزيون يلقى الجوال تلقائيًا إذا \"عنوان اللابتوب\" فيه على تلقائي، وإلا اكتب عنوان الجوال اللي فوق.", 12f, color = Color.parseColor("#8C94A4"))))

        // Game + region
        root.addView(header("اللعبة ومكان الترجمة"))
        val group = RadioGroup(this).apply { orientation = RadioGroup.HORIZONTAL }
        for (p in GameProfile.ALL) {
            group.addView(RadioButton(this).apply {
                id = View.generateViewId(); text = p.name; setTextColor(Color.WHITE)
                isChecked = p.id == settings.profileId
                setOnCheckedChangeListener { _, on -> if (on) { settings.profileId = p.id; if (!settings.customRegion) settings.region = android.graphics.RectF(p.region); save() } }
            })
        }
        regionBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val custom = CheckBox(this).apply {
            text = "تعديل مكان الترجمة يدويًا"; setTextColor(Color.WHITE)
            isChecked = settings.customRegion
            setOnCheckedChangeListener { _, on -> settings.customRegion = on; save(); regionBox.visibility = if (on) View.VISIBLE else View.GONE }
        }
        regionBox.visibility = if (settings.customRegion) View.VISIBLE else View.GONE
        regionBox.addView(slider("من الأعلى", (settings.region.top * 100).toInt()) { v -> val h = settings.region.height(); settings.region.top = v / 100f; settings.region.bottom = (v / 100f + h).coerceAtMost(1f); save() })
        regionBox.addView(slider("الارتفاع", (settings.region.height() * 100).toInt()) { v -> settings.region.bottom = (settings.region.top + v / 100f).coerceAtMost(1f); save() })
        regionBox.addView(slider("من اليسار", (settings.region.left * 100).toInt()) { v -> val w = settings.region.width(); settings.region.left = v / 100f; settings.region.right = (v / 100f + w).coerceAtMost(1f); save() })
        regionBox.addView(slider("العرض", (settings.region.width() * 100).toInt()) { v -> settings.region.right = (settings.region.left + v / 100f).coerceAtMost(1f); save() })
        root.addView(card(group, custom, regionBox,
            text("التطبيق يقرأ بس الجزء اللي فيه الترجمة من صورة اللعبة. GTA VI مضبوطة جاهزة. شوف \"آخر ما قرأته\" فوق عشان تتأكد.", 12f, color = Color.parseColor("#8C94A4"))))

        // Font size
        root.addView(header("حجم الخط على التلفزيون"))
        root.addView(card(slider("الحجم", settings.fontSize, max = 90, min = 24) { v -> settings.fontSize = v; save() }))

        // Glossary
        root.addView(header("قاموس إضافي"))
        val gloss = EditText(this).apply {
            setText(settings.userGlossary)
            hint = "Jason = جيسون"
            minLines = 3
            gravity = Gravity.TOP or Gravity.START
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            textDirection = View.TEXT_DIRECTION_LTR
            setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
            addTextChangedListener(watcher { settings.userGlossary = it; save() })
        }
        root.addView(card(gloss, text("كل سطر: الكلمة بالإنجليزي = ترجمتها. أسماء GTA VI الأساسية موجودة من قبل.", 12f, color = Color.parseColor("#8C94A4"))))

        // Help
        root.addView(header("طريقة الاستخدام"))
        root.addView(card(text(
            "١. ركّب تطبيق PlayTranslate في التلفزيون.\n" +
            "٢. ادخل حساب PSN ثاني في PS Remote Play على الجوال.\n" +
            "٣. الصق مفتاح DeepL واضغط \"اختبار التلفزيون\" مرة وحدة.\n" +
            "٤. اضغط \"ابدأ الترجمة\" ثم افتح PS Remote Play وخلّ الجوال بالعرض.\n" +
            "٥. خلّ الجوال على الشاحن طول اللعب. للإيقاف: من الإشعار أو من هنا.", 14f)))

        // Cache + about
        cacheView = text("", 14f)
        root.addView(card(cacheView, button("مسح الجمل المحفوظة") {
            if (!Status.running) { TranslationCache(Reader.cacheFile(this)).clear(); refreshCache() }
        }, text("الإصدار ${BuildConfig.VERSION_NAME} · فكرة وتطوير عبدالله الغزواني", 12f, color = Color.parseColor("#8C94A4"))))

        refreshCache()
        tick()
    }

    override fun onPause() {
        super.onPause()
        save()
        stopTest()
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun save() = settings.save(this)

    private fun tick() {
        val running = Status.running
        statusView.text = when {
            !running -> "⏸ الترجمة متوقفة"
            Status.tvCount > 0 -> "● الترجمة شغّالة · التلفزيون متصل ✓"
            else -> "● الترجمة شغّالة · ينتظر التلفزيون…"
        }
        statusView.setTextColor(if (running) Color.parseColor("#6ED3C9") else Color.parseColor("#A6ADBB"))
        val parts = mutableListOf<String>()
        if (Status.lastEnglish.isNotEmpty()) parts.add("آخر ما قرأته:\n${Status.lastEnglish}")
        if (Status.lastArabic.isNotEmpty()) parts.add(Status.lastArabic)
        if (Status.lastError.isNotEmpty()) parts.add("⚠ ${Status.lastError}")
        if (running && Status.msPerRead > 0) parts.add("سرعة القراءة: ${Status.msPerRead} ملّي ثانية")
        lastView.text = parts.joinToString("\n\n")
        lastView.visibility = if (parts.isEmpty()) View.GONE else View.VISIBLE
        startButton.text = if (running) "إيقاف الترجمة" else "ابدأ الترجمة"
        testButton.isEnabled = !running
        ipView.text = "عنوان الجوال: ${Net.localIPv4() ?: "غير متصل بالواي فاي"}"
        tester?.let { testView.text = if (it.clientCount > 0) "التلفزيون متصل ✓ لازم تشوف نص التجربة عليه." else "شغّل تطبيق PlayTranslate في التلفزيون… (الاختبار يوقف بعد دقيقة)" }
        main.postDelayed({ tick() }, 1000)
    }

    private fun refreshCache() {
        Thread {
            val n = TranslationCache(Reader.cacheFile(this)).size
            main.post { cacheView.text = "جمل محفوظة: $n" }
        }.start()
    }

    // ---- capture

    private fun toggleCapture() {
        if (Status.running) {
            startService(Intent(this, CaptureService::class.java).setAction(CaptureService.ACTION_STOP))
            return
        }
        stopTest()
        save()
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFY)
            return
        }
        askProjection()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        // The notification only shows that translation is on; carry on either way.
        if (requestCode == REQ_NOTIFY) askProjection()
    }

    private fun askProjection() {
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        @Suppress("DEPRECATION") startActivityForResult(mpm.createScreenCaptureIntent(), REQ_CAPTURE)
    }

    @Deprecated("Activity result API is not used in this dependency-free screen")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION") super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_CAPTURE) return
        if (resultCode != RESULT_OK || data == null) {
            Status.lastError = "ما وافقت على مشاركة الشاشة، فالترجمة ما بدأت."
            return
        }
        val intent = Intent(this, CaptureService::class.java)
            .putExtra(CaptureService.EXTRA_CODE, resultCode)
            .putExtra(CaptureService.EXTRA_DATA, data)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
    }

    // ---- TV test

    private fun toggleTest() {
        if (tester != null) { stopTest(); return }
        val srv = DisplayServer("PlayTranslate (Android)", settings.tvStyle())
        srv.start()
        srv.show(listOf(mapOf("speaker" to "PlayTranslate", "text" to "هذا نص تجربة من الجوال. إذا شفته فوق صورة اللعبة فكل شيء جاهز.")))
        tester = srv
        testButton.text = "إيقاف الاختبار"
        val stop = Runnable { stopTest() }
        testStop = stop
        main.postDelayed(stop, 60_000)
    }

    private fun stopTest() {
        testStop?.let { main.removeCallbacks(it) }
        testStop = null
        val srv = tester ?: return
        tester = null
        Thread { srv.hide(); srv.stop() }.start()
        testButton.text = "اختبار التلفزيون"
        testView.text = ""
    }

    private fun checkKey() {
        keyMessage.text = "جاري الفحص…"
        val key = settings.deeplKey
        Thread {
            val msg = try {
                val (used, limit) = DeepL(key).usage()
                if (limit > 0) "المفتاح يشتغل ✓ استخدمت $used من $limit حرف هذا الشهر." else "المفتاح يشتغل ✓"
            } catch (e: Exception) {
                e.message ?: e.toString()
            }
            main.post { keyMessage.text = msg }
        }.start()
    }

    // ---- small view helpers

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun text(s: String, size: Float, bold: Boolean = false, color: Int = Color.WHITE) = TextView(this).apply {
        text = s
        setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(4), 0, dp(4))
        textDirection = View.TEXT_DIRECTION_FIRST_STRONG
    }

    private fun header(s: String) = text(s, 18f, bold = true, color = accent).apply { setPadding(0, dp(22), 0, dp(6)) }

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { onClick() }
    }

    private fun rounded(color: Int, radius: Float) = GradientDrawable().apply {
        setColor(color); cornerRadius = radius * resources.displayMetrics.density
    }

    private fun card(vararg views: View) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(Color.parseColor("#171A21"), 14f)
        setPadding(dp(14), dp(10), dp(14), dp(10))
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(10) }
        for (v in views) addView(v)
    }

    private fun slider(label: String, value: Int, max: Int = 100, min: Int = 0, onChange: (Int) -> Unit): View {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val valueView = text("$value", 14f).apply { minWidth = dp(40) }
        row.addView(text(label, 14f).apply { minWidth = dp(80) })
        row.addView(SeekBar(this).apply {
            this.max = max - min
            progress = (value - min).coerceIn(0, max - min)
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar, p: Int, fromUser: Boolean) {
                    if (fromUser) { valueView.text = "${p + min}"; onChange(p + min) }
                }
                override fun onStartTrackingTouch(sb: SeekBar) {}
                override fun onStopTrackingTouch(sb: SeekBar) {}
            })
        }, LinearLayout.LayoutParams(0, -2, 1f))
        row.addView(valueView)
        return row
    }

    private fun watcher(onText: (String) -> Unit) = object : TextWatcher {
        override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
        override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        override fun afterTextChanged(s: Editable?) = onText(s?.toString() ?: "")
    }

    companion object {
        private const val REQ_CAPTURE = 1
        private const val REQ_NOTIFY = 2
    }
}
