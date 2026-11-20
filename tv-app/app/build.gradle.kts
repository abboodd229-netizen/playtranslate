plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.playtranslate.tv"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.playtranslate.tv"
        minSdk = 26 // Android 8: TYPE_APPLICATION_OVERLAY
        targetSdk = 34
        versionCode = 3
        versionName = "0.2.1"
    }

    signingConfigs {
        // Uses PT_KEYSTORE / PT_KEYSTORE_PASSWORD / PT_KEY_ALIAS / PT_KEY_PASSWORD when set (CI always
        // sets them); otherwise the local Android debug key, so Android Studio builds just work.
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
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
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
}
