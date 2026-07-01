# Source this before any Android/Gradle/cargo-ndk build step:
#   source /Users/alphaintern/Projects/lsat_app/mobile-env.sh
export JAVA_HOME="$HOME/tools-dl/jdk17/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/29.0.14206865"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$HOME/.cargo/bin:$PATH"
# Where the Android app repos live (kept out of the desktop git workspace):
export MOBILE_DIR="$HOME/lsat-mobile"
# The Android backend must build/extract its OWN protoc; a leaked PROTOC pointing
# at the desktop tree makes `configure` skip the extract:protoc target.
unset PROTOC PROTOC_BINARY
