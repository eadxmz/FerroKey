package com.ferrostb.keyboard;

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
