plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.playtranslate.phone"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.playtranslate.phone"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    signingConfigs {
        // Same key as the TV app (CI sets PT_KEYSTORE...); the local debug key otherwise.
        create("release") {
            val ks = System.getenv("PT_KEYSTORE")
            if (ks != null && file(ks).exists()) {
                storeFile = file(ks)
                storePassword = System.getenv("PT_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("PT_KEY_ALIAS")
                keyPassword = System.getenv("PT_KEY_PASSWORD")
            } else {
                val debug = signingConfigs.getByName("debug")
                storeFile = debug.storeFile
                storePassword = debug.storePassword
                keyAlias = debug.keyAlias
                keyPassword = debug.keyPassword
            }
        }
    }

    buildTypes {
        release {
            // ML Kit and Java-WebSocket are kept whole; the APK stays small enough.
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    sourceSets {
        // The same game packs the laptop imports (packs/gta-vi.json ...).
        getByName("main").assets.srcDir("../../../packs")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.java-websocket:Java-WebSocket:1.5.7")
    // On-device English text recognition, model bundled in the APK (works offline, free).
    implementation("com.google.mlkit:text-recognition:16.0.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
