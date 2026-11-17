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
version = "0.3.0"
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
    Lower = 0,
    Upper = 1,
    Numbers = 2,
    Symbols = 3,
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
            0 => 3,  // Top Floating Pill: [PREV, NEXT, DONE]
            1 => 10, // Q W E R T Y U I O P (or 1..0 / symbols)
            2 => 9,  // A S D F G H J K L
            3 => 9,  // SHIFT/#+= Z X C V B N M BKSP
            4 => 4,  // [123/ABC] [#+=] [SPACE] [ENTER]
            _ => 10,
        }
    }

    fn move_cursor(&mut self, d_row: isize, d_col: isize) {
        let old_row = self.row;
        let new_row = (self.row as isize + d_row).clamp(0, 4) as usize;
        self.row = new_row;

        if old_row != new_row {
            self.col = match (old_row, new_row) {
                (1, 0) => match self.col {
                    0..=1 => 0,
                    2..=6 => 1,
                    _ => 2,
                },
                (0, 1) => match self.col {
                    0 => 0,
                    1 => 2,
                    _ => 9,
                },
                (1, 2) => self.col.min(8),
                (2, 1) => self.col,
                (2, 3) => self.col,
                (3, 2) => self.col,
                (3, 4) => match self.col {
                    0 => 0,
                    1 => 1,
                    2..=6 => 2,
                    _ => 3,
                },
                (4, 3) => match self.col {
                    0 => 0,
                    1 => 1,
                    2 => 4,
                    _ => 8,
                },
                _ => self.col.min(Self::row_len(new_row) - 1),
            };
        } else if d_col != 0 {
            let len = Self::row_len(self.row) as isize;
            self.col = (self.col as isize + d_col).rem_euclid(len) as usize;
        }
    }

    fn key_label(&self, r: usize, c: usize) -> &'static str {
        const PILL: [&str; 3] = ["PREV", "NEXT", "DONE"];

        const ALPHA_R1: [&str; 10] = ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"];
        const ALPHA_R2: [&str; 9] = ["A", "S", "D", "F", "G", "H", "J", "K", "L"];
        const ALPHA_R3: [&str; 9] = ["SHIFT", "Z", "X", "C", "V", "B", "N", "M", "BKSP"];

        const NUM_R1: [&str; 10] = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
        const NUM_R2: [&str; 9] = ["-", "/", ":", ";", "(", ")", "$", "&", "@"];
        const NUM_R3: [&str; 9] = ["#+=_L", ".", ",", "?", "!", "'", "\"", "_", "BKSP"];

        const SYM_R1: [&str; 10] = ["[", "]", "{", "}", "#", "%", "^", "*", "+", "="];
        const SYM_R2: [&str; 9] = ["_", "\\", "|", "~", "<", ">", "€", "£", "₹"];
        const SYM_R3: [&str; 9] = ["123_L", ".", ",", "?", "!", "'", "\"", "•", "BKSP"];

        match r {
            0 => PILL[c.min(2)],
            1 => match self.layer {
                Layer::Lower | Layer::Upper => ALPHA_R1[c],
                Layer::Numbers => NUM_R1[c],
                Layer::Symbols => SYM_R1[c],
            },
            2 => match self.layer {
                Layer::Lower | Layer::Upper => ALPHA_R2[c],
                Layer::Numbers => NUM_R2[c],
                Layer::Symbols => SYM_R2[c],
            },
            3 => match self.layer {
                Layer::Lower | Layer::Upper => ALPHA_R3[c],
                Layer::Numbers => NUM_R3[c],
                Layer::Symbols => SYM_R3[c],
            },
            4 => match c {
                0 => match self.layer {
                    Layer::Numbers | Layer::Symbols => "ABC",
                    _ => "123",
                },
                1 => match self.layer {
                    Layer::Symbols => "123",
                    _ => "#+=",
                },
                2 => "SPACE",
                _ => "ENTER",
            },
            _ => "",
        }
    }

    fn activate_current(&mut self) -> String {
        let key = self.key_label(self.row, self.col);
        match key {
            "PREV" => "CURSOR_LEFT".to_string(),
            "NEXT" => "CURSOR_RIGHT".to_string(),
            "DONE" => "HIDE".to_string(),
            "SHIFT" => {
                self.layer = match self.layer {
                    Layer::Lower => Layer::Upper,
                    Layer::Upper => Layer::Lower,
                    Layer::Numbers => Layer::Symbols,
                    Layer::Symbols => Layer::Numbers,
                };
                "REDRAW".to_string()
            }
            "123" | "123_L" => {
                self.layer = Layer::Numbers;
                "REDRAW".to_string()
            }
            "#+=" | "#+=_L" => {
                self.layer = Layer::Symbols;
                "REDRAW".to_string()
            }
            "ABC" => {
                self.layer = Layer::Lower;
                "REDRAW".to_string()
            }
            "BKSP" => "BACKSPACE".to_string(),
            "SPACE" => "COMMIT: ".to_string(),
            "ENTER" => "SUBMIT".to_string(),
            ch => {
                let out = if self.layer == Layer::Lower {
                    ch.to_ascii_lowercase()
                } else {
                    ch.to_string()
                };
                "COMMIT:".to_string() + &out
            }
        }
    }

    fn serialize_grid(&self) -> String {
        let layer_id = self.layer as u8;
        let mut out = format!("{},{},{}\n", self.row, self.col, layer_id);
        for r in 0..=4 {
            let len = Self::row_len(r);
            let mut items = Vec::with_capacity(len);
            for c in 0..len {
                items.push(self.key_label(r, c));
            }
            out.push_str(&items.join("\t"));
            if r < 4 {
                out.push('\n');
            }
        }
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
const KEYCODE_NUMPAD_ENTER: jint = 160;

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
        KEYCODE_DPAD_CENTER | KEYCODE_ENTER | KEYCODE_NUMPAD_ENTER => state.activate_current(),
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
    android:versionCode="3"
    android:versionName="1.2">

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
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.inputmethodservice.InputMethodService;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.Window;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.widget.FrameLayout;

public class FerroKeyboardService extends InputMethodService {
    static {
        System.loadLibrary("ferrokey");
    }

    public static native String nativeOnKey(int keyCode);
    public static native String nativeGetGrid();

    private LiquidGlassView glassView;
    private boolean keepKeyboardOpen = false;
    private boolean allowHideWindow = false;
    private InputConnection cachedIc = null;

    @Override
    public boolean onEvaluateFullscreenMode() {
        return false;
    }

    @Override
    public boolean onEvaluateInputViewShown() {
        if (keepKeyboardOpen) {
            return true;
        }
        return super.onEvaluateInputViewShown();
    }

    @Override
    public boolean onShowInputRequested(int flags, boolean configChange) {
        keepKeyboardOpen = true;
        allowHideWindow = false;
        return true;
    }

    @Override
    public void onWindowShown() {
        super.onWindowShown();
        keepKeyboardOpen = true;
        allowHideWindow = false;
        InputConnection ic = getCurrentInputConnection();
        if (ic != null) {
            cachedIc = ic;
        }
        if (glassView != null) {
            glassView.invalidate();
        }
    }

    @Override
    public void onStartInput(EditorInfo attribute, boolean restarting) {
        super.onStartInput(attribute, restarting);
        InputConnection ic = getCurrentInputConnection();
        if (ic != null && attribute != null && attribute.inputType != 0) {
            cachedIc = ic;
        }
    }

    @Override
    public void onFinishInputView(boolean finishingInput) {
        if (!allowHideWindow && keepKeyboardOpen) {
            return;
        }
        super.onFinishInputView(finishingInput);
    }

    @Override
    public void hideWindow() {
        if (keepKeyboardOpen && !allowHideWindow) {
            return;
        }
        keepKeyboardOpen = false;
        allowHideWindow = false;
        super.hideWindow();
    }

    private void dismissKeyboardExplicitly() {
        keepKeyboardOpen = false;
        allowHideWindow = true;
        requestHideSelf(0);
        super.hideWindow();
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

        // Wide TV-scaled floating container (64% width, 45% height)
        int cardW = (int) (screenW * 0.64f);
        int cardH = (int) (screenH * 0.45f);
        int bottomMargin = (int) (screenH * 0.03f);

        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(cardW, cardH);
        params.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
        params.bottomMargin = bottomMargin;

        glassView = new LiquidGlassView(this);
        container.addView(glassView, params);
        return container;
    }

    private boolean isDpadOrImeKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_DPAD_UP
                || keyCode == KeyEvent.KEYCODE_DPAD_DOWN
                || keyCode == KeyEvent.KEYCODE_DPAD_LEFT
                || keyCode == KeyEvent.KEYCODE_DPAD_RIGHT
                || keyCode == KeyEvent.KEYCODE_DPAD_CENTER
                || keyCode == KeyEvent.KEYCODE_ENTER
                || keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER
                || keyCode == KeyEvent.KEYCODE_DEL;
    }

    private InputConnection activeConnection() {
        InputConnection ic = getCurrentInputConnection();
        return (ic != null) ? ic : cachedIc;
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (!keepKeyboardOpen && !isInputViewShown()) {
            return super.onKeyDown(keyCode, event);
        }

        if (keyCode == KeyEvent.KEYCODE_BACK) {
            dismissKeyboardExplicitly();
            return true;
        }

        if (!isDpadOrImeKey(keyCode)) {
            return super.onKeyDown(keyCode, event);
        }

        String action = nativeOnKey(keyCode);
        if ("PASS".equals(action)) {
            return true;
        }

        if ("HIDE".equals(action)) {
            dismissKeyboardExplicitly();
            return true;
        }

        InputConnection ic = activeConnection();
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
            } else if ("SUBMIT".equals(action)) {
                EditorInfo info = getCurrentInputEditorInfo();
                int actionId = (info != null) ? (info.imeOptions & EditorInfo.IME_MASK_ACTION) : EditorInfo.IME_ACTION_NONE;
                if (actionId != EditorInfo.IME_ACTION_NONE && actionId != EditorInfo.IME_ACTION_UNSPECIFIED) {
                    ic.performEditorAction(actionId);
                } else {
                    ic.performEditorAction(EditorInfo.IME_ACTION_SEARCH);
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ENTER));
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_ENTER));
                }
                dismissKeyboardExplicitly();
                return true;
            }
        }

        if (glassView != null) {
            glassView.invalidate();
        }
        return true;
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keepKeyboardOpen || isInputViewShown()) {
            if (keyCode == KeyEvent.KEYCODE_BACK || isDpadOrImeKey(keyCode)) {
                return true;
            }
        }
        return super.onKeyUp(keyCode, event);
    }

    @Override
    public boolean onKeyLongPress(int keyCode, KeyEvent event) {
        if ((keepKeyboardOpen || isInputViewShown()) && isDpadOrImeKey(keyCode)) {
            return true;
        }
        return super.onKeyLongPress(keyCode, event);
    }

    private static class LiquidGlassView extends View {
        private final Paint pillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint pillRimPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint cardPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint cardRimPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint keyPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint keyTopRimPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint focusPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint focusRimPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint shiftActivePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint subTextPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint iconPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF rect = new RectF();
        private final Path path = new Path();

        public LiquidGlassView(Context context) {
            super(context);
            setLayerType(LAYER_TYPE_SOFTWARE, null);

            pillRimPaint.setStyle(Paint.Style.STROKE);
            pillRimPaint.setStrokeWidth(1.6f);

            cardRimPaint.setStyle(Paint.Style.STROKE);
            cardRimPaint.setStrokeWidth(1.8f);

            keyTopRimPaint.setStyle(Paint.Style.STROKE);
            keyTopRimPaint.setStrokeWidth(1.2f);
            keyTopRimPaint.setColor(0x35FFFFFF);

            focusRimPaint.setStyle(Paint.Style.STROKE);
            focusRimPaint.setStrokeWidth(2.4f);
            focusRimPaint.setColor(0xFFFFFFFF);

            shiftActivePaint.setColor(0xEEFFFFFF);

            textPaint.setColor(0xFFF8FAFC);
            textPaint.setTextAlign(Paint.Align.CENTER);
            textPaint.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));

            subTextPaint.setColor(0x99E2E8F0);
            subTextPaint.setTextAlign(Paint.Align.RIGHT);
            subTextPaint.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));

            iconPaint.setStyle(Paint.Style.STROKE);
            iconPaint.setStrokeCap(Paint.Cap.ROUND);
            iconPaint.setStrokeJoin(Paint.Join.ROUND);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            String raw = nativeGetGrid();
            String[] lines = raw.split("\n");
            if (lines.length < 6) return;

            String[] header = lines[0].split(",");
            int focusRow = Integer.parseInt(header[0]);
            int focusCol = Integer.parseInt(header[1]);
            int layerId = Integer.parseInt(header[2]);
            boolean shiftActive = (layerId == 1);

            float w = getWidth();
            float h = getHeight();
            float outerPad = 10f;

            // 1. Top Detached Liquid Glass Accessory Pill (focusRow == 0)
            float pillH = h * 0.13f;
            float pillMarginX = outerPad + (w - outerPad * 2f) * 0.02f;
            rect.set(pillMarginX, outerPad, w - pillMarginX, outerPad + pillH);
            float pillRadius = pillH * 0.5f;

            pillPaint.setShader(new LinearGradient(
                    0, rect.top, 0, rect.bottom,
                    new int[]{0xA81A2636, 0x960E1620},
                    null,
                    Shader.TileMode.CLAMP
            ));
            pillPaint.setShadowLayer(12f, 0f, 4f, 0x77000000);
            canvas.drawRoundRect(rect, pillRadius, pillRadius, pillPaint);

            pillRimPaint.setShader(new LinearGradient(
                    rect.left, rect.top, rect.right, rect.bottom,
                    new int[]{0x99FFFFFF, 0x33FFFFFF, 0x88FFFFFF},
                    null,
                    Shader.TileMode.CLAMP
            ));
            canvas.drawRoundRect(rect, pillRadius, pillRadius, pillRimPaint);

            float pillBtnW = pillH * 1.35f;
            float pillCy = rect.centerY();
            float[] pillCentersX = new float[]{
                    rect.left + pillBtnW * 0.55f,
                    rect.left + pillBtnW * 1.65f,
                    rect.right - pillBtnW * 0.55f
            };

            for (int c = 0; c < 3; c++) {
                float cx = pillCentersX[c];
                boolean isFocused = (focusRow == 0 && focusCol == c);
                rect.set(cx - pillBtnW * 0.45f, outerPad + 4f, cx + pillBtnW * 0.45f, outerPad + pillH - 4f);
                if (isFocused) {
                    focusPaint.setShader(new LinearGradient(
                            rect.left, rect.top, rect.left, rect.bottom,
                            0x77FFFFFF, 0x44FFFFFF, Shader.TileMode.CLAMP
                    ));
                    canvas.drawRoundRect(rect, pillRadius, pillRadius, focusPaint);
                    canvas.drawRoundRect(rect, pillRadius, pillRadius, focusRimPaint);
                } else if (c == 0) {
                    keyPaint.setShader(new LinearGradient(
                            rect.left, rect.top, rect.left, rect.bottom,
                            0x28FFFFFF, 0x18FFFFFF, Shader.TileMode.CLAMP
                    ));
                    canvas.drawRoundRect(rect, pillRadius, pillRadius, keyPaint);
                }

                iconPaint.setStrokeWidth(2.6f);
                iconPaint.setColor(isFocused ? 0xFFFFFFFF : 0xCCFFFFFF);
                float s = pillH * 0.16f;
                path.reset();
                if (c == 0) {
                    // Up/Prev chevron (^)
                    path.moveTo(cx - s * 1.2f, pillCy + s * 0.45f);
                    path.lineTo(cx, pillCy - s * 0.65f);
                    path.lineTo(cx + s * 1.2f, pillCy + s * 0.45f);
                } else if (c == 1) {
                    // Down/Next chevron (v)
                    path.moveTo(cx - s * 1.2f, pillCy - s * 0.45f);
                    path.lineTo(cx, pillCy + s * 0.65f);
                    path.lineTo(cx + s * 1.2f, pillCy - s * 0.45f);
                } else {
                    // Done Checkmark (✓)
                    path.moveTo(cx - s * 1.2f, pillCy + s * 0.1f);
                    path.lineTo(cx - s * 0.3f, pillCy + s * 0.95f);
                    path.lineTo(cx + s * 1.35f, pillCy - s * 0.85f);
                }
                canvas.drawPath(path, iconPaint);
            }

            // 2. Main Dark Frosted Glass Keyboard Card
            float cardTop = outerPad + pillH + (h * 0.025f);
            float cardBot = h - outerPad;
            rect.set(outerPad, cardTop, w - outerPad, cardBot);
            float cardRadius = 34f;

            cardPaint.setShader(new LinearGradient(
                    0, cardTop, 0, cardBot,
                    new int[]{0xDC101822, 0xE60A0F16, 0xF006090E},
                    new float[]{0f, 0.5f, 1f},
                    Shader.TileMode.CLAMP
            ));
            cardPaint.setShadowLayer(18f, 0f, 8f, 0x99000000);
            canvas.drawRoundRect(rect, cardRadius, cardRadius, cardPaint);

            cardRimPaint.setShader(new LinearGradient(
                    0, cardTop, w, cardBot,
                    new int[]{0x77FFFFFF, 0x22FFFFFF, 0x44FFFFFF},
                    null,
                    Shader.TileMode.CLAMP
            ));
            canvas.drawRoundRect(rect, cardRadius, cardRadius, cardRimPaint);

            // 3. Key Grid Area (Rows 1..4 map to lines[2..5])
            float padX = outerPad + 16f;
            float padY = 14f;
            float gridTop = cardTop + padY;
            float gridBot = cardBot - padY;
            float gridH = gridBot - gridTop;
            float gridW = (w - outerPad * 2f) - 32f;

            float rowH = gridH / 4f;
            float unitW = gridW / 10f;
            float gapX = 8.0f;
            float gapY = 8.5f;
            float keyCorner = 15f;

            subTextPaint.setTextSize(rowH * 0.22f);

            for (int r = 1; r <= 4; r++) {
                // FIXED: lines[r + 1] maps r=1..4 to Rust rows 1..4
                String[] keys = lines[r + 1].split("\t");
                float yTop = gridTop + (r - 1) * rowH + gapY * 0.5f;
                float yBot = gridTop + r * rowH - gapY * 0.5f;

                for (int c = 0; c < keys.length; c++) {
                    float xLeft;
                    float xRight;

                    if (r == 1) {
                        // Row 1: 10 equal keys (Q..P or 1..0)
                        xLeft = padX + c * unitW;
                        xRight = xLeft + unitW;
                    } else if (r == 2) {
                        // Row 2: 9 keys indented by 0.5u on both sides (A..L)
                        xLeft = padX + (0.5f + c) * unitW;
                        xRight = xLeft + unitW;
                    } else if (r == 3) {
                        // Row 3: [SHIFT/#+= (1.35u)] + 7 keys (Z..M) + [BKSP (1.35u)]
                        if (c == 0) {
                            xLeft = padX;
                            xRight = padX + unitW * 1.35f;
                        } else if (c == 8) {
                            xRight = padX + gridW;
                            xLeft = xRight - unitW * 1.35f;
                        } else {
                            xLeft = padX + (1.5f + (c - 1)) * unitW;
                            xRight = xLeft + unitW;
                        }
                    } else {
                        // Row 4: [123/ABC (1.35u)] [#+= (1.35u)] [SPACE (4.8u)] [ENTER (2.5u)]
                        if (c == 0) {
                            xLeft = padX;
                            xRight = padX + unitW * 1.35f;
                        } else if (c == 1) {
                            xLeft = padX + unitW * 1.35f;
                            xRight = padX + unitW * 2.70f;
                        } else if (c == 2) {
                            xLeft = padX + unitW * 2.70f;
                            xRight = padX + unitW * 7.50f;
                        } else {
                            xLeft = padX + unitW * 7.50f;
                            xRight = padX + gridW;
                        }
                    }

                    rect.set(xLeft + gapX * 0.5f, yTop, xRight - gapX * 0.5f, yBot);
                    String rawLabel = keys[c];
                    String label = rawLabel.replace("_L", "");
                    boolean isFocused = (r == focusRow && c == focusCol);
                    boolean isShiftKey = "SHIFT".equals(label);

                    if (isFocused) {
                        rect.inset(-1.8f, -1.8f);
                        focusPaint.setShader(new LinearGradient(
                                rect.left, rect.top, rect.left, rect.bottom,
                                0x70FFFFFF, 0x40FFFFFF, Shader.TileMode.CLAMP
                        ));
                        focusPaint.setShadowLayer(12f, 0f, 3f, 0x66FFFFFF);
                        canvas.drawRoundRect(rect, keyCorner, keyCorner, focusPaint);
                        canvas.drawRoundRect(rect, keyCorner, keyCorner, focusRimPaint);
                    } else if (isShiftKey && shiftActive) {
                        canvas.drawRoundRect(rect, keyCorner, keyCorner, shiftActivePaint);
                    } else {
                        keyPaint.setShader(new LinearGradient(
                                rect.left, rect.top, rect.left, rect.bottom,
                                0x3AFFFFFF, 0x24FFFFFF, Shader.TileMode.CLAMP
                        ));
                        canvas.drawRoundRect(rect, keyCorner, keyCorner, keyPaint);
                        canvas.drawRoundRect(rect, keyCorner, keyCorner, keyTopRimPaint);
                    }

                    float cx = rect.centerX();
                    float cy = rect.centerY();

                    if ("SHIFT".equals(label)) {
                        drawShiftIcon(canvas, cx, cy, rowH * 0.22f, (isShiftKey && shiftActive && !isFocused) ? 0xFF0F172A : 0xFFFFFFFF);
                    } else if ("BKSP".equals(label)) {
                        drawBackspaceIcon(canvas, cx, cy, rowH * 0.22f, 0xFFFFFFFF);
                    } else if ("ENTER".equals(label)) {
                        drawReturnIcon(canvas, cx, cy, rowH * 0.22f, 0xFFFFFFFF);
                    } else if ("SPACE".equals(label)) {
                        String badge = (layerId == 1) ? "CAPS" : (layerId == 2) ? "123" : (layerId == 3) ? "SYM" : "EN";
                        canvas.drawText(badge, rect.right - 12f, rect.bottom - 9f, subTextPaint);
                    } else {
                        if (label.length() >= 3) {
                            textPaint.setTextSize(rowH * 0.30f);
                        } else {
                            textPaint.setTextSize(rowH * 0.40f);
                        }
                        Paint.FontMetrics fm = textPaint.getFontMetrics();
                        float textY = cy - (fm.ascent + fm.descent) / 2f;
                        canvas.drawText(label, cx, textY, textPaint);
                    }
                }
            }
        }

        private void drawShiftIcon(Canvas canvas, float cx, float cy, float s, int color) {
            Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
            p.setStyle(Paint.Style.FILL);
            p.setColor(color);
            path.reset();
            path.moveTo(cx, cy - s * 0.95f);
            path.lineTo(cx + s * 0.95f, cy + s * 0.05f);
            path.lineTo(cx + s * 0.42f, cy + s * 0.05f);
            path.lineTo(cx + s * 0.42f, cy + s * 0.85f);
            path.lineTo(cx - s * 0.42f, cy + s * 0.85f);
            path.lineTo(cx - s * 0.42f, cy + s * 0.05f);
            path.lineTo(cx - s * 0.95f, cy + s * 0.05f);
            path.close();
            canvas.drawPath(path, p);
        }

        private void drawBackspaceIcon(Canvas canvas, float cx, float cy, float s, int color) {
            iconPaint.setStrokeWidth(2.3f);
            iconPaint.setColor(color);
            path.reset();
            path.moveTo(cx - s * 1.15f, cy);
            path.lineTo(cx - s * 0.45f, cy - s * 0.72f);
            path.lineTo(cx + s * 1.05f, cy - s * 0.72f);
            path.lineTo(cx + s * 1.05f, cy + s * 0.72f);
            path.lineTo(cx - s * 0.45f, cy + s * 0.72f);
            path.close();
            canvas.drawPath(path, iconPaint);

            float xOff = cx + s * 0.25f;
            float d = s * 0.32f;
            canvas.drawLine(xOff - d, cy - d, xOff + d, cy + d, iconPaint);
            canvas.drawLine(xOff + d, cy - d, xOff - d, cy + d, iconPaint);
        }

        private void drawReturnIcon(Canvas canvas, float cx, float cy, float s, int color) {
            iconPaint.setStrokeWidth(2.4f);
            iconPaint.setColor(color);
            path.reset();
            path.moveTo(cx + s * 0.95f, cy - s * 0.55f);
            path.lineTo(cx + s * 0.95f, cy + s * 0.25f);
            path.lineTo(cx - s * 0.95f, cy + s * 0.25f);
            canvas.drawPath(path, iconPaint);

            path.reset();
            path.moveTo(cx - s * 0.45f, cy - s * 0.22f);
            path.lineTo(cx - s * 0.95f, cy + s * 0.25f);
            path.lineTo(cx - s * 0.45f, cy + s * 0.72f);
            canvas.drawPath(path, iconPaint);
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

          "$BT/aapt2" compile res/xml/method.xml -o build/
          "$BT/aapt2" link -o build/unsigned.apk \
            -I "$PLATFORM/android.jar" \
            --manifest AndroidManifest.xml \
            --java build/classes \
            build/xml_method.xml.flat

          javac -source 1.8 -target 1.8 \
            -bootclasspath "$PLATFORM/android.jar" \
            -d build/classes \
            java/com/ferrostb/keyboard/FerroKeyboardService.java \
            build/classes/com/ferrostb/keyboard/R.java

          "$BT/d8" --lib "$PLATFORM/android.jar" \
            --output build/apk \
            $(find build/classes -name "*.class")

          cp jniLibs/armeabi-v7a/libferrokey.so build/apk/lib/armeabi-v7a/
          cp jniLibs/arm64-v8a/libferrokey.so build/apk/lib/arm64-v8a/

          cd build/apk
          zip -u ../unsigned.apk classes.dex
          zip -u -0 -r ../unsigned.apk lib/
          cd ../..

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

print("[+] FerroKey v0.3 (Fixed row alignment, TV-wide scaling, 123/#+= buttons) generated!")