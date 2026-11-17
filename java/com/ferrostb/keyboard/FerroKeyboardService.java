package com.ferrostb.keyboard;

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
