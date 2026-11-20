import SwiftUI

struct TranslateView: View {
    /// Switches to the PlayStation tab (built-in Remote Play).
    var openPlayStation: () -> Void = {}
    @State private var settings = Settings.load()
    @State private var status = BroadcastStatus.load()
    @State private var keyMessage = ""
    @State private var checkingKey = false
    @State private var cacheCount = 0
    @StateObject private var tester = TVTester()
    @Environment(\.scenePhase) private var scenePhase
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
    }

    var body: some View {
        NavigationView {
            Form {
                statusSection
                startSection
                keySection
                tvSection
                gameSection
                readingSection
                glossarySection
                helpSection
                aboutSection
            }
            .navigationTitle("PlayTranslate")
        }
        .navigationViewStyle(.stack)
        .onAppear {
            tester.askLocalNetworkOnce()
            cacheCount = TranslationCache().count
        }
        .onReceive(timer) { _ in status = BroadcastStatus.load() }
        .onReceive(NotificationCenter.default.publisher(for: FrameTap.sessionStarted)) { _ in
            tester.stop()   // the translation needs the TV port
        }
        .onChange(of: settings) { newValue in newValue.save() }
        .onChange(of: scenePhase) { phase in
            if phase != .active { tester.stop() }
        }
    }

    // MARK: sections

    private var statusSection: some View {
        Section {
            if !AppGroup.isAvailable {
                Label("التثبيت ما فعّل مشاركة الإعدادات بين التطبيق وقارئ الشاشة. أعد التثبيت عن طريق SideStore أو AltStore.",
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundColor(.orange)
            }
            HStack {
                Circle().fill(status.isLive ? Color.green : Color.gray).frame(width: 12, height: 12)
                Text(status.isLive ? "الترجمة شغّالة" : "الترجمة متوقفة").bold()
                Spacer()
                if status.isLive {
                    Text(status.tvCount > 0 ? "التلفزيون متصل ✓" : "ينتظر التلفزيون…")
                        .foregroundColor(status.tvCount > 0 ? .green : .secondary)
                }
            }
            if status.isLive && status.msPerRead > 0 {
                Text("سرعة القراءة: \(status.msPerRead) ملّي ثانية").font(.footnote).foregroundColor(.secondary)
            }
            if !status.lastEnglish.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("آخر ما قرأته:").font(.caption).foregroundColor(.secondary)
                    Text(status.lastEnglish).environment(\.layoutDirection, .leftToRight)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !status.lastArabic.isEmpty {
                        Text(status.lastArabic).bold()
                    }
                }
            }
            if !status.lastError.isEmpty {
                Text(status.lastError).foregroundColor(.red)
            }
        } header: { Text("الحالة") }
    }

    private var startSection: some View {
        Section {
            Button {
                tester.stop()
                openPlayStation()
            } label: {
                Label("ابدأ: افتح البلايستيشن", systemImage: "gamecontroller.fill")
                    .font(.title3.bold())
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            Text("الريموت بلاي صار داخل التطبيق. من تبويب \"البلايستيشن\" اربط جهازك أول مرة، وبعدها اضغط عليه عشان يبدأ البث. الترجمة تشتغل لحالها مع أول صورة وتطلع على التلفزيون، وتوقف لما توقف البث. خلّ التطبيق مفتوح والجوال على الشاحن.")
                .font(.footnote).foregroundColor(.secondary)
            DisclosureGroup("الطريقة القديمة: تسجيل الشاشة مع تطبيق سوني") {
                HStack(spacing: 12) {
                    Button {
                        tester.stop()   // frees the TV port for the screen reader
                        BroadcastLauncher.shared.open()
                    } label: {
                        Label("تسجيل الشاشة", systemImage: "record.circle")
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.bordered)
                    SystemBroadcastButton().frame(width: 44, height: 44)
                }
                Text("اختر \"PlayTranslate\" ثم \"بدء البث\"، وبعدها افتح PS Remote Play. إذا طلعت الصورة سوداء استخدم الطريقة اللي فوق.")
                    .font(.footnote).foregroundColor(.secondary)
            }
        }
    }

    private var keySection: some View {
        Section {
            SecureField("الصق مفتاح DeepL هنا", text: $settings.deeplKey)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .environment(\.layoutDirection, .leftToRight)
            Button(checkingKey ? "جاري الفحص…" : "فحص المفتاح") { checkKey() }
                .disabled(checkingKey || settings.deeplKey.isEmpty)
            if !keyMessage.isEmpty { Text(keyMessage).font(.footnote) }
        } header: { Text("مفتاح الترجمة (DeepL)") } footer: {
            Text("نفس المفتاح المجاني اللي في برنامج اللابتوب يشتغل هنا. المجاني فيه ٥٠٠ ألف حرف بالشهر، والجمل المكررة ما تنحسب لأنها تنحفظ في الجوال.")
        }
    }

    private var tvSection: some View {
        Section {
            Button(tester.running ? "إيقاف الاختبار" : "اختبار التلفزيون") {
                if tester.running { tester.stop() } else { tester.start(settings: settings) }
            }
            .disabled(status.isLive)
            if tester.running {
                Text(tester.tvCount > 0 ? "التلفزيون متصل ✓ لازم تشوف نص التجربة عليه."
                                        : "شغّل تطبيق PlayTranslate في التلفزيون… (الاختبار يقف بعد دقيقة)")
                    .foregroundColor(tester.tvCount > 0 ? .green : .secondary)
            }
            if let ip = Net.localIPv4() {
                Text("عنوان الجوال: \(ip)").environment(\.layoutDirection, .leftToRight)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        } header: { Text("التلفزيون") } footer: {
            Text("الجوال والتلفزيون لازم يكونون على نفس الواي فاي. تطبيق التلفزيون يلقى الجوال تلقائيًا إذا كان \"عنوان اللابتوب\" فيه على تلقائي. إذا ما لقاه، اكتب عنوان الجوال اللي فوق في تطبيق التلفزيون. وإذا طلب الجوال إذن \"الشبكة المحلية\" اضغط سماح.")
        }
    }

    private var gameSection: some View {
        Section {
            Picker("اللعبة", selection: $settings.profileID) {
                ForEach(GameProfile.all) { Text($0.name).tag($0.id) }
            }
            Toggle("تعديل مكان الترجمة يدويًا", isOn: $settings.customRegion)
            if settings.customRegion {
                regionSlider("من الأعلى", value: $settings.region.origin.y, range: 0...0.95)
                regionSlider("الارتفاع", value: $settings.region.size.height, range: 0.03...1)
                regionSlider("من اليسار", value: $settings.region.origin.x, range: 0...0.95)
                regionSlider("العرض", value: $settings.region.size.width, range: 0.05...1)
                Button("رجوع لإعداد اللعبة") { settings.region = settings.profile.region }
            }
            RegionPreview(region: settings.effectiveRegion)
                .frame(height: 140)
                .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
        } header: { Text("اللعبة ومكان الترجمة") } footer: {
            Text("المربع الأزرق هو الجزء اللي يقرأه التطبيق من صورة اللعبة. خلّه على مكان الترجمة الإنجليزية في اللعبة بس.")
        }
    }

    private func regionSlider(_ title: String, value: Binding<CGFloat>, range: ClosedRange<CGFloat>) -> some View {
        HStack {
            Text(title).frame(width: 80, alignment: .leading)
            Slider(value: value, in: range).environment(\.layoutDirection, .leftToRight)
            Text("\(Int(value.wrappedValue * 100))٪").monospacedDigit().frame(width: 44)
        }
    }

    private var readingSection: some View {
        Section {
            Toggle("قراءة دقيقة", isOn: $settings.accurateOCR)
            Stepper("حجم الخط على التلفزيون: \(settings.fontSize)", value: $settings.fontSize, in: 24...90, step: 4)
        } header: { Text("القراءة والعرض") } footer: {
            Text("القراءة الدقيقة أفضل للترجمة. إذا وقف البث لحاله، طفّها (تستهلك ذاكرة وبطارية أقل). أي تغيير هنا يطبق من التشغيل الجاي.")
        }
    }

    private var glossarySection: some View {
        Section {
            TextEditor(text: $settings.userGlossary)
                .frame(minHeight: 90)
                .environment(\.layoutDirection, .leftToRight)
                .font(.body.monospaced())
        } header: { Text("قاموس إضافي") } footer: {
            Text("كل سطر: الكلمة بالإنجليزي = ترجمتها. مثال: Jason = جيسون. أسماء GTA VI الأساسية موجودة من قبل.")
        }
    }

    private var helpSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                Text("١. ركّب تطبيق PlayTranslate في التلفزيون (نفس تطبيق اللابتوب).")
                Text("٢. شغّل البلايستيشن بحسابك اللي تلعب فيه، وخلّه هو والجوال على نفس الواي فاي.")
                Text("٣. الصق مفتاح DeepL واضغط \"اختبار التلفزيون\" مرة وحدة.")
                Text("٤. في تبويب \"البلايستيشن\": سجّل دخول بحساب PSN ثاني (مو حسابك اللي تلعب فيه) واربط الجهاز مرة وحدة.")
                Text("٥. اضغط على البلايستيشن عشان يبدأ البث، والعب على التلفزيون بيدك العادية.")
                Text("٦. خلّ الجوال على الشاحن والتطبيق مفتوح طول اللعب.")
            }
            .font(.callout)
        } header: { Text("طريقة الاستخدام") }
    }

    private var aboutSection: some View {
        Section {
            HStack {
                Text("جمل محفوظة: \(cacheCount)")
                Spacer()
                Button("مسح") {
                    TranslationCache().clear()
                    cacheCount = 0
                }
                .disabled(status.isLive)
            }
            Text("الإصدار \(version) — صنع عبدالله الغزواني").font(.footnote).foregroundColor(.secondary)
        }
    }

    // MARK: actions

    private func checkKey() {
        checkingKey = true
        keyMessage = ""
        let key = settings.deeplKey
        DispatchQueue.global(qos: .userInitiated).async {
            var message: String
            do {
                let (used, limit) = try DeepL(key: key).usage()
                message = limit > 0 ? "المفتاح يشتغل ✓ استخدمت \(used) من \(limit) حرف هذا الشهر." : "المفتاح يشتغل ✓"
            } catch {
                message = (error as? TranslateError)?.message ?? error.localizedDescription
            }
            DispatchQueue.main.async {
                keyMessage = message
                checkingKey = false
            }
        }
    }
}

/// A 16:9 game picture with the read area drawn on it.
struct RegionPreview: View {
    let region: CGRect

    var body: some View {
        GeometryReader { geo in
            let w = min(geo.size.width, geo.size.height * 16 / 9)
            let h = w * 9 / 16
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 6).fill(Color.black.opacity(0.85))
                Rectangle()
                    .fill(Color.blue.opacity(0.35))
                    .overlay(Rectangle().stroke(Color.blue, lineWidth: 2))
                    .frame(width: region.width * w, height: region.height * h)
                    .offset(x: region.minX * w, y: region.minY * h)
            }
            .frame(width: w, height: h)
            .environment(\.layoutDirection, .leftToRight)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
