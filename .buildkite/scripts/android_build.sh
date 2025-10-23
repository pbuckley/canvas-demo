#!/usr/bin/env bash
set -euo pipefail

echo "--- :android: Gradle Build"
echo ""
echo "Starting a Gradle Daemon"
sleep 1
echo "Gradle build daemon started in 1.2s"
echo ""
echo "> Task :app:preBuild UP-TO-DATE"
echo "> Task :app:preDebugBuild UP-TO-DATE"
sleep 1
echo "> Task :app:compileDebugKotlin"
echo "  Compiling 89 Kotlin source files"
echo "    MainActivity.kt"
echo "    HomeFragment.kt"
echo "    SettingsFragment.kt"
echo "    ProfileFragment.kt"
echo "    NetworkService.kt"
echo "    DataRepository.kt"
echo "    ViewModels (8 files)"
sleep 2
echo "> Task :app:compileDebugJavaWithJavac"
echo "> Task :app:mergeDebugResources"
echo "  Merging resources from 47 modules"
sleep 1
echo "> Task :app:processDebugManifest"
echo "> Task :app:processDebugResources"
echo "> Task :app:mergeDebugAssets"
sleep 1
echo "> Task :app:compressDebugAssets"
echo "> Task :app:packageDebug"
echo "  Creating APK: app/build/outputs/apk/debug/app-debug.apk"
sleep 1
echo "> Task :app:assembleDebug"
echo ""

# Create mock artifact
mkdir -p app/build/outputs/apk/debug
echo "Mock APK file" > app/build/outputs/apk/debug/app-debug.apk

echo "BUILD SUCCESSFUL in 12s"
echo "34 actionable tasks: 34 executed"
echo ""
echo "+++ :white_check_mark: Android APK built successfully"
echo "APK: app-debug.apk (8.4 MB)"
echo "Min SDK: 24 (Android 7.0)"
echo "Target SDK: 34 (Android 14)"
