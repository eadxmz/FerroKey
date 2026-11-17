import os

FILES = {
    ".gitignore": r"""/target
/build
/jniLibs
*.apk
*.idsig
*.keystore
""",

    "Cargo.toml": r"""[package]
name = "ferrokey"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
jni = "0.21"

[profile.release]
opt-level = "z"
lto = true
codegen-units = 1
strip = true
panic = "abort"
""",

    "src/lib.rs": r"""use jni::objects::JClass;
use jni::sys::{jint, jstring};
use jni::JNIEnv;
use std::sync::Mutex;

#[derive(Clone, Copy, PartialEq)]
enum Layer {
    Lower,
    Upper,
    Symbols,
}

struct KeyboardState {
    row: usize,
    col: usize,
    layer: Layer,
}

impl KeyboardState {
    const fn new() -> Self {
        Self {
            row: 1,
            col: 0,
            layer: Layer::Lower,
        }
    }

    fn row_len(row: usize) -> usize {
        match row {
            0..=3 => 10,
            4 => 6, // [SYM, LEFT, SPACE, RIGHT, CLR, ENTER]
            _ => 10,
        }
    }

    fn move_cursor(&mut self, d_row: isize, d_col: isize) {
        let old_row = self.row;
        let new_row = (self.row as isize + d_row).clamp(0, 4) as usize;
        self.row = new_row;

        if old_row != new_row {
            if new_row == 4 {
                self.col = match self.col {
                    0..=1 => 0, // SYM
                    2 => 1,     // LEFT
                    3..=6 => 2, // SPACE
                    7 => 3,     // RIGHT
                    8 => 4,     // CLR
                    _ => 5,     // ENTER
                };
            } else if old_row == 4 {
                self.col = match self.col {
                    0 => 0,
                    1 => 2,
                    2 => 4,
                    3 => 7,
                    4 => 8,
                    _ => 9,
                };
            }
        } else {
            let len = Self::row_len(self.row) as isize;
            self.col = (self.col as isize + d_col).rem_euclid(len) as usize;
        }
    }

    fn key_at(&self, r: usize, c: usize) -> &'static str {
        const LOWER: [[&str; 10]; 4] = [
            ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
            ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
            ["a", "s", "d", "f", "g", "h", "j", "k", "l", "-"],
            ["SHIFT", "z", "x", "c", "v", "b", "n", "m", ".", "BKSP"],
        ];
        const UPPER: [[&str; 10]; 4] = [
            ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
            ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
            ["A", "S", "D", "F", "G", "H", "J", "K", "L", "_"],
            ["SHIFT", "Z", "X", "C", "V", "B", "N", "M", ",", "BKSP"],
        ];
        const SYM: [[&str; 10]; 4] = [
            ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")"],
            ["~", "`", "|", "/", "\\", "=", "+", "[", "]", "?"],
            [":", ";", "\"", "'", "<", ">", "{", "}", "_", "-"],
            ["SHIFT", "€", "£", "₹", "©", "®", "°", "•", "…", "BKSP"],
        ];
        const BOTTOM: [&str; 6] = ["?!#", "◀", "SPACE", "▶", "CLR", "⏎"];

        if r == 4 {
            return BOTTOM[c.min(5)];
        }
        match self.layer {
            Layer::Lower => LOWER[r][c],
            Layer::Upper => UPPER[r][c],
            Layer::Symbols => SYM[r][c],
        }
    }

    fn activate_current(&mut self) -> String {
        let key = self.key_at(self.row, self.col);
        match key {
            "SHIFT" => {
                self.layer = match self.layer {
                    Layer::Lower => Layer::Upper,
                    Layer::Upper => Layer::Lower,
                    Layer::Symbols => Layer::Lower,
                };
                "REDRAW".to_string()
            }
            "?!#" => {
                self.layer = match self.layer {
                    Layer::Symbols => Layer::Lower,
                    _ => Layer::Symbols,
                };
                "REDRAW".to_string()
            }
            "BKSP" => "BACKSPACE".to_string(),
            "SPACE" => "COMMIT: ".to_string(),
            "◀" => "CURSOR_LEFT".to_string(),
            "▶" => "CURSOR_RIGHT".to_string(),
            "CLR" => "CLEAR".to_string(),
            "⏎" => "SUBMIT".to_string(),
            ch => format!("COMMIT:{}", ch),
        }
    }

    fn serialize_grid(&self) -> String {
        let mut out = format!("{},{}\n", self.row, self.col);
        for r in 0..4 {
            let mut row_items = Vec::with_capacity(10);
            for c in 0..10 {
                row_items.push(self.key_at(r, c));
            }
            out.push_str(&row_items.join("\t"));
            out.push('\n');
        }
        let mut bot_items = Vec::with_capacity(6);
        for c in 0..6 {
            bot_items.push(self.key_at(4, c));
        }
        out.push_str(&bot_items.join("\t"));
        out
    }
}

static STATE: Mutex<KeyboardState> = Mutex::new(KeyboardState::new());

const KEYCODE_DPAD_UP: jint = 19;
const KEYCODE_DPAD_DOWN: jint = 20;
const KEYCODE_DPAD_LEFT: jint = 21;
const KEYCODE_DPAD_RIGHT: jint = 22;
const KEYCODE_DPAD_CENTER: jint = 23;
const KEYCODE_ENTER: jint = 66;
const KEYCODE_DEL: jint = 67;

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeOnKey(
    env: JNIEnv,
    _class: JClass,
    key_code: jint,
) -> jstring {
    let mut state = STATE.lock().unwrap();
    let response = match key_code {
        KEYCODE_DPAD_UP => {
            state.move_cursor(-1, 0);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_DOWN => {
            state.move_cursor(1, 0);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_LEFT => {
            state.move_cursor(0, -1);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_RIGHT => {
            state.move_cursor(0, 1);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_CENTER | KEYCODE_ENTER => state.activate_current(),
        KEYCODE_DEL => "BACKSPACE".to_string(),
        _ => "PASS".to_string(),
    };
    env.new_string(response).unwrap().into_raw()
}

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeGetGrid(
    env: JNIEnv,
    _class: JClass,
) -> jstring {
    let state = STATE.lock().unwrap();
    let payload = state.serialize_grid();
    env.new_string(payload).unwrap().into_raw()
}
""",

    "AndroidManifest.xml": r"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.ferrostb.keyboard"
    android:versionCode="1"
    android:versionName="1.0">

    <uses-sdk android:minSdkVersion="26" android:targetSdkVersion="30" />

    <application
        android:label="FerroKey Liquid Glass"
        android:hardwareAccelerated="true">

        <service
            android:name=".FerroKeyboardService"
            android:label="FerroKey Liquid Glass"
            android:permission="android.permission.BIND_INPUT_METHOD"
            android:exported="true">
            <intent-filter>
                <action android:name="android.view.InputMethod" />
            </intent-filter>
            <meta-data
                android:name="android.view.im"
                android:resource="@xml/method" />
        </service>
    </application>
</manifest>
""",

    "res/xml/method.xml": r"""<?xml version="1.0" encoding="utf-8"?>
<input-method xmlns:android="http://schemas.android.com/apk/res/android"
    android:isDefault="true">
    <subtype
        android:label="English (US)"
        android:imeSubtypeLocale="en_US"
        android:imeSubtypeMode="keyboard" />
</input-method>
""",

    "java/com/ferrostb/keyboard/FerroKeyboardService.java": r"""package com.ferrostb.keyboard;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.inputmethodservice.InputMethodService;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.Window;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.ExtractedText;
import android.view.inputmethod.ExtractedTextRequest;
import android.view.inputmethod.InputConnection;
import android.widget.FrameLayout;

public class FerroKeyboardService extends InputMethodService {
    static {
        System.loadLibrary("ferrokey");
    }

    public static native String nativeOnKey(int keyCode);
    public static native String nativeGetGrid();

    private LiquidGlassView glassView;

    @Override
    public boolean onEvaluateFullscreenMode() {
        return false;
    }

    @Override
    public void onComputeInsets(Insets outInsets) {
        super.onComputeInsets(outInsets);
        if (getWindow() != null && getWindow().getWindow() != null) {
            int decorHeight = getWindow().getWindow().getDecorView().getHeight();
            outInsets.contentTopInsets = decorHeight;
            outInsets.visibleTopInsets = decorHeight;
            outInsets.touchableInsets = Insets.TOUCHABLE_INSETS_FRAME;
        }
    }

    @Override
    public View onCreateInputView() {
        Window win = getWindow().getWindow();
        if (win != null) {
            win.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        }

        FrameLayout container = new FrameLayout(this);
        container.setBackgroundColor(Color.TRANSPARENT);

        int screenW = getResources().getDisplayMetrics().widthPixels;
        int screenH = getResources().getDisplayMetrics().heightPixels;

        int cardW = (int) (screenW * 0.56f);
        int cardH = (int) (screenH * 0.38f);
        int bottomMargin = (int) (screenH * 0.045f);

        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(cardW, cardH);
        params.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
        params.bottomMargin = bottomMargin;

        glassView = new LiquidGlassView(this);
        container.addView(glassView, params);
        return container;
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        EditorInfo info = getCurrentInputEditorInfo();
        if (!isInputViewShown() || info == null || info.inputType == InputType.TYPE_NULL) {
            return super.onKeyDown(keyCode, event);
        }

        if (keyCode == KeyEvent.KEYCODE_BACK) {
            requestHideSelf(0);
            return true;
        }

        String action = nativeOnKey(keyCode);
        if ("PASS".equals(action)) {
            return super.onKeyDown(keyCode, event);
        }

        InputConnection ic = getCurrentInputConnection();
        if (ic != null) {
            if (action.startsWith("COMMIT:")) {
                ic.commitText(action.substring(7), 1);
            } else if ("BACKSPACE".equals(action)) {
                ic.deleteSurroundingText(1, 0);
            } else if ("CURSOR_LEFT".equals(action)) {
                ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DPAD_LEFT));
                ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_DPAD_LEFT));
            } else if ("CURSOR_RIGHT".equals(action)) {
                ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DPAD_RIGHT));
                ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_DPAD_RIGHT));
            } else if ("CLEAR".equals(action)) {
                ExtractedText et = ic.getExtractedText(new ExtractedTextRequest(), 0);
                if (et != null && et.text != null) {
                    ic.setSelection(0, et.text.length());
                    ic.commitText("", 1);
                }
            } else if ("SUBMIT".equals(action)) {
                int actionId = info.imeOptions & EditorInfo.IME_MASK_ACTION;
                if (actionId != EditorInfo.IME_ACTION_NONE) {
                    ic.performEditorAction(actionId);
                } else {
                    ic.performEditorAction(EditorInfo.IME_ACTION_SEARCH);
                }
                requestHideSelf(0);
            }
        }

        if (glassView != null) {
            glassView.invalidate();
        }
        return true;
    }

    private static class LiquidGlassView extends View {
        private final Paint cardPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint rimOuterPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint rimInnerPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint keyPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint keyBorderPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint focusPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint focusRimPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF rect = new RectF();

        public LiquidGlassView(Context context) {
            super(context);
            setLayerType(LAYER_TYPE_SOFTWARE, null);

            rimOuterPaint.setStyle(Paint.Style.STROKE);
            rimOuterPaint.setStrokeWidth(2.2f);

            rimInnerPaint.setStyle(Paint.Style.STROKE);
            rimInnerPaint.setStrokeWidth(1.2f);
            rimInnerPaint.setColor(0x38FFFFFF);

            keyBorderPaint.setStyle(Paint.Style.STROKE);
            keyBorderPaint.setStrokeWidth(1.3f);
            keyBorderPaint.setColor(0x40FFFFFF);

            focusRimPaint.setStyle(Paint.Style.STROKE);
            focusRimPaint.setStrokeWidth(2.5f);
            focusRimPaint.setColor(0xEEBAE6FD);

            textPaint.setColor(0xFFF8FAFC);
            textPaint.setTextAlign(Paint.Align.CENTER);
            textPaint.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float w = getWidth();
            float h = getHeight();
            float pad = 14f;

            rect.set(pad, pad, w - pad, h - pad);
            cardPaint.setShader(new LinearGradient(
                    0, pad, 0, h - pad,
                    new int[]{0xCC1E293B, 0xB80F172A, 0xCC090D16},
                    new float[]{0f, 0.55f, 1f},
                    Shader.TileMode.CLAMP
            ));
            cardPaint.setShadowLayer(18f, 0f, 8f, 0x99000000);
            canvas.drawRoundRect(rect, 32f, 32f, cardPaint);

            rimOuterPaint.setShader(new LinearGradient(
                    0, pad, w, h - pad,
                    new int[]{0xAAFFFFFF, 0x5538BDF8, 0x22FFFFFF, 0x7738BDF8},
                    null,
                    Shader.TileMode.CLAMP
            ));
            canvas.drawRoundRect(rect, 32f, 32f, rimOuterPaint);

            rect.inset(3f, 3f);
            canvas.drawRoundRect(rect, 29f, 29f, rimInnerPaint);

            String raw = nativeGetGrid();
            String[] lines = raw.split("\n");
            if (lines.length < 6) return;

            String[] coords = lines[0].split(",");
            int focusRow = Integer.parseInt(coords[0]);
            int focusCol = Integer.parseInt(coords[1]);

            float innerPad = pad + 16f;
            float availW = w - (innerPad * 2f);
            float availH = h - (innerPad * 2f);
            float rowH = availH / 5f;
            float gap = 7f;

            textPaint.setTextSize(rowH * 0.34f);

            for (int r = 0; r < 5; r++) {
                String[] keys = lines[r + 1].split("\t");
                float yTop = innerPad + r * rowH + (gap * 0.5f);
                float yBot = innerPad + (r + 1) * rowH - (gap * 0.5f);

                float totalUnits = (r == 4) ? 10f : keys.length;
                float unitW = availW / totalUnits;
                float curX = innerPad;

                for (int c = 0; c < keys.length; c++) {
                    float span = (r == 4 && c == 2) ? 5f : 1f;
                    float kW = unitW * span;
                    rect.set(curX + gap * 0.5f, yTop, curX + kW - gap * 0.5f, yBot);
                    curX += kW;

                    boolean isFocused = (r == focusRow && c == focusCol);
                    if (isFocused) {
                        rect.inset(-2f, -2f);
                        focusPaint.setShader(new LinearGradient(
                                rect.left, rect.top, rect.left, rect.bottom,
                                0x9938BDF8, 0x550284C7, Shader.TileMode.CLAMP
                        ));
                        focusPaint.setShadowLayer(14f, 0f, 3f, 0xAA38BDF8);
                        canvas.drawRoundRect(rect, 18f, 18f, focusPaint);
                        canvas.drawRoundRect(rect, 18f, 18f, focusRimPaint);
                        textPaint.setColor(0xFFFFFFFF);
                    } else {
                        keyPaint.setShader(new LinearGradient(
                                rect.left, rect.top, rect.left, rect.bottom,
                                0x36FFFFFF, 0x12FFFFFF, Shader.TileMode.CLAMP
                        ));
                        canvas.drawRoundRect(rect, 15f, 15f, keyPaint);
                        canvas.drawRoundRect(rect, 15f, 15f, keyBorderPaint);
                        textPaint.setColor(0xFFE2E8F0);
                    }

                    Paint.FontMetrics fm = textPaint.getFontMetrics();
                    float textY = rect.centerY() - (fm.ascent + fm.descent) / 2f;
                    canvas.drawText(keys[c], rect.centerX(), textY, textPaint);
                }
            }
        }
    }
}
""",

    ".github/workflows/build.yml": r"""name: Build FerroKey Liquid Glass APK

on:
  push:
    branches: [ "main", "master" ]
  workflow_dispatch:

jobs:
  build-apk:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Install Rust toolchain & Android targets
        uses: dtolnay/rust-toolchain@stable
        with:
          targets: armv7-linux-androideabi,aarch64-linux-android

      - name: Rust Cache
        uses: Swatinem/rust-cache@v2

      - name: Install cargo-ndk
        uses: taiki-e/install-action@v2
        with:
          tool: cargo-ndk

      - name: Compile Rust Liquid Glass Core (.so)
        run: |
          cargo ndk -t armeabi-v7a -t arm64-v8a -o ./jniLibs build --release

      - name: Package & Sign Android APK
        run: |
          BT=$(ls -d "$ANDROID_HOME/build-tools/"* | sort -V | tail -n 1)
          PLATFORM=$(ls -d "$ANDROID_HOME/platforms/"* | sort -V | tail -n 1)

          mkdir -p build/classes build/apk/lib/armeabi-v7a build/apk/lib/arm64-v8a

          # 1. Compile XML resources & link base APK
          "$BT/aapt2" compile res/xml/method.xml -o build/
          "$BT/aapt2" link -o build/unsigned.apk \
            -I "$PLATFORM/android.jar" \
            --manifest AndroidManifest.xml \
            --java build/classes \
            build/xml_method.xml.flat

          # 2. Compile Java shim to DEX
          javac -source 1.8 -target 1.8 \
            -bootclasspath "$PLATFORM/android.jar" \
            -d build/classes \
            java/com/ferrostb/keyboard/FerroKeyboardService.java \
            build/classes/com/ferrostb/keyboard/R.java

          "$BT/d8" --lib "$PLATFORM/android.jar" \
            --output build/apk \
            $(find build/classes -name "*.class")

          # 3. Bundle DEX + Rust native libraries into APK
          cp jniLibs/armeabi-v7a/libferrokey.so build/apk/lib/armeabi-v7a/
          cp jniLibs/arm64-v8a/libferrokey.so build/apk/lib/arm64-v8a/

          cd build/apk
          zip -u ../unsigned.apk classes.dex
          zip -u -0 -r ../unsigned.apk lib/
          cd ../..

          # 4. Align & Sign APK
          "$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk

          keytool -genkey -v \
            -keystore debug.keystore \
            -storepass android \
            -alias androiddebugkey \
            -keypass android \
            -keyalg RSA \
            -keysize 2048 \
            -validity 10000 \
            -dname "CN=FerroSTB,O=Android,C=US"

          "$BT/apksigner" sign \
            --ks debug.keystore \
            --ks-pass pass:android \
            --out ferrokey-liquid-glass.apk \
            build/aligned.apk

      - name: Upload Signed APK Artifact
        uses: actions/upload-artifact@v4
        with:
          name: ferrokey-liquid-glass-apk
          path: ferrokey-liquid-glass.apk
"""
}

for path, content in FILES.items():
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content.strip() + "\n")

print("[+] FerroKey Liquid Glass + GitHub Actions workflow (with Rust Cache) generated!")